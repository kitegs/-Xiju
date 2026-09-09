"""Recompute deterministic report facts; preview before any existing report write."""
import asyncio
from copy import deepcopy
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from .commercial import _sha256, record_report_artifact
from .database import get_session
from .models import Dataset, DatasetVersion, Report, ReportVersion
from .report_claims import fingerprint, subjects
from .schemas import ReportDocument
from .services import assess_report_quality, build_report, profile_dataframe, read_dataframe, storage_path
from .team import audit, report_and_actor

router = APIRouter(prefix='/api/v1/reports', tags=['report-repair'])


class RepairApply(BaseModel):
    proposal_hash: str
    approved: Literal[True]


def recompute(version, title, prompt, semantics=None, requirements=None):
    path=storage_path(version.storage_key)
    if not path.is_file(): raise ValueError('数据版本文件不存在，无法重新核算')
    if _sha256(path)!=version.content_hash: raise ValueError('数据文件与原报告版本哈希不一致，请重新导入为新版本')
    frame=read_dataframe(version.storage_key)
    fresh=build_report(frame,profile_dataframe(frame),title,prompt,semantics)
    if requirements:
        from .report_requirements import compose_report
        from .report_claims import seal_claims
        compose_report(fresh, frame, requirements)
        seal_claims(fresh)
    if _sha256(path)!=version.content_hash: raise ValueError('重算期间数据文件发生变化，请重试')
    return fresh


def repair_candidate(original, fresh):
    candidate=original.model_copy(deep=True)
    changes=[]
    def change(target,field,old,new):
        if old!=new: changes.append({'target':target,'field':field,'before':old,'after':new})
    change('summary','summary',candidate.summary,fresh.summary)
    candidate.summary=fresh.summary
    fresh_findings={item.id:item for item in fresh.findings}
    for item in candidate.findings:
        if item.id not in fresh_findings: continue
        new=fresh_findings[item.id]
        for field in ('headline','statement','business_impact','recommendation','caveats','evidence_ids'):
            change(item.id,field,getattr(item,field),getattr(new,field))
            setattr(item,field,deepcopy(getattr(new,field)))
    fresh_blocks={item.id:item for item in fresh.blocks}
    for item in candidate.blocks:
        if item.id not in fresh_blocks or item.kind not in {'paragraph','insight','callout'}: continue
        new=fresh_blocks[item.id]
        for field in ('content','evidence_ids'):
            change(item.id,field,getattr(item,field),getattr(new,field))
            setattr(item,field,deepcopy(getattr(new,field)))
    # Preserve custom blocks/charts and their order. Never certify their free-form text.
    replacements={item.id:item for item in fresh.evidence}
    candidate.evidence=[replacements.pop(e.id,e) for e in candidate.evidence]
    candidate.evidence.extend(replacements.values())
    # JavaScript serializes 1253100.0 as 1253100. Preserve edits, but canonicalize
    # equal values to the freshly computed representation before hashing them.
    fresh_charts = {chart.id: chart for chart in fresh.charts}
    for chart in candidate.charts:
        reference = fresh_charts.get(chart.id)
        if reference and chart.data == reference.data:
            chart.data = deepcopy(reference.data)
    change('evidence','evidence', [e.model_dump(mode='json') for e in original.evidence], [e.model_dump(mode='json') for e in candidate.evidence])
    candidate.metadata['claim_baseline']=deepcopy(fresh.metadata['claim_baseline'])
    candidate.claims=deepcopy(fresh.claims)
    # Retain certificates only for unchanged appendices backed by unchanged evidence.
    prior=original.metadata.get('claim_baseline') or {}
    baseline=candidate.metadata['claim_baseline']
    current_evidence={e.id:fingerprint(e.model_dump(mode='json')) for e in candidate.evidence}
    for kind,key,text,refs,category in subjects(candidate):
        name=f'{kind}:{key}'
        old=(prior.get('subjects') or {}).get(name)
        if name in baseline['subjects'] or not old or old['text']!=text or old['evidence_ids']!=refs: continue
        if all(ref in (prior.get('evidence') or {}) and current_evidence.get(ref)==prior['evidence'][ref] for ref in refs):
            baseline['subjects'][name]=deepcopy(old)
            for ref in refs: baseline['evidence'][ref]=prior['evidence'][ref]
    candidate.quality=assess_report_quality(candidate)
    return candidate,changes


async def proposal_for(report, session):
    version=await session.get(DatasetVersion,report.dataset_version_id) if report.dataset_version_id else None
    if not version or version.workspace_id!=report.workspace_id:
        raise HTTPException(409,'报告缺少可追溯的数据版本，请先绑定数据重新生成报告')
    try:
        dataset=await session.get(Dataset,version.dataset_id)
        fresh=await asyncio.to_thread(recompute,version,report.title,(report.document.get('metadata') or {}).get('prompt','核验经营报告'),(version.profile or {}).get('semantics', {}),(report.document.get('metadata') or {}).get('report_requirements'))
    except (ValueError,FileNotFoundError) as exc:
        raise HTTPException(409,str(exc)) from exc
    original=ReportDocument.model_validate(report.document)
    candidate,changes=repair_candidate(original,fresh)
    stable=candidate.model_dump(mode='json',exclude={'quality'})
    token=fingerprint({'original':report.document,'title':report.title,'version':version.id,'data_hash':version.content_hash,'candidate':stable})
    return candidate, {'proposal_hash':token,'dataset_version_id':version.id,'data_hash':version.content_hash,
        'changes':changes,'quality':candidate.quality.model_dump(mode='json'),
        'note':'基于原报告数据版本全量重算；已编辑的系统结论将按差异恢复。新增自定义段落、图表和排序保留，不自动认证。0 模型 Token。'}


@router.post('/{report_id}/repair/preview')
async def preview(report_id:str,x_actor_id:str|None=Header(default=None),session:AsyncSession=Depends(get_session)):
    report,_,_=await report_and_actor(report_id,x_actor_id,session,'report.edit')
    _,proposal=await proposal_for(report,session)
    return proposal


@router.post('/{report_id}/repair/apply')
async def apply(report_id:str,payload:RepairApply,x_actor_id:str|None=Header(default=None),session:AsyncSession=Depends(get_session)):
    report,actor,_=await report_and_actor(report_id,x_actor_id,session,'report.edit')
    old=deepcopy(report.document)
    candidate,proposal=await proposal_for(report,session)
    if payload.proposal_hash!=proposal['proposal_hash']:
        raise HTTPException(409,'报告或数据已变化，请重新预览修复方案')
    result=await session.execute(update(Report).where(Report.id==report.id,Report.document==old,
        Report.title==report.title,Report.deleted_at.is_(None)).values(document=candidate.model_dump(mode='json')).execution_options(synchronize_session=False))
    if result.rowcount!=1: raise HTTPException(409,'报告已被其他操作修改，请重新预览')
    session.add(ReportVersion(report_id=report.id,title=report.title,document=old))
    await session.refresh(report)
    await record_report_artifact(session,report)
    await audit(session,report.workspace_id,actor.id,'report.repair.apply','report',report.id,
        {'dataset_version_id':report.dataset_version_id,'change_count':len(proposal['changes'])})
    await session.commit()
    return {'report_id':report.id,'quality':candidate.quality.model_dump(mode='json')}
