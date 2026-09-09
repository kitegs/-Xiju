"""Report CRUD, history and export API. Existing chart editing routes remain compatible."""
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_session
from .models import Report, ReportVersion, Dataset
from .schemas import ReportOut, ReportCreate, ReportRename, ReportUpdate, ReportDocument, ReportVersionOut, ReportQualityReport
from .services import assess_report_quality
from .commercial import record_report_artifact
from .exporting import build_docx
from .team import actor_for, require, report_and_actor, audit
from .presenters import as_report, as_report_version

router = APIRouter()

@router.get("/api/v1/reports", response_model=list[ReportOut])
async def list_reports(workspace_id: str, deleted: bool = False, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    _, membership = await actor_for(session, workspace_id, x_actor_id); require(membership, "report.view")
    result = await session.scalars(select(Report).where(Report.workspace_id == workspace_id, Report.deleted_at.is_not(None) if deleted else Report.deleted_at.is_(None)).order_by(Report.updated_at.desc()))
    return [as_report(item) for item in result]


@router.post("/api/v1/reports", response_model=ReportOut, status_code=201)
async def create_report(payload: ReportCreate, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    actor, membership = await actor_for(session, payload.workspace_id, x_actor_id)
    require(membership, "report.edit")
    title = payload.title.strip()
    if not title: raise HTTPException(422, "标题不能为空")
    source = None
    if payload.source_report_id:
        source, _, _ = await report_and_actor(payload.source_report_id, x_actor_id, session, "report.view")
        if source.workspace_id != payload.workspace_id: raise HTTPException(404, "源报告不属于当前工作区")
    dataset_id = source.dataset_id if source else payload.dataset_id
    if dataset_id:
        dataset = await session.get(Dataset, dataset_id)
        if not dataset or dataset.workspace_id != payload.workspace_id: raise HTTPException(404, "数据集不存在")
    document = ReportDocument.model_validate(deepcopy(source.document)) if source else ReportDocument(title=title, summary="", blocks=[], charts=[], evidence=[])
    document.title = title
    if source: document.metadata["copied_from_report_id"] = source.id
    document.quality = assess_report_quality(document)
    report = Report(workspace_id=payload.workspace_id, dataset_id=dataset_id, title=title, document=document.model_dump(mode="json"),
        project_id=source.project_id if source else None, dataset_version_id=source.dataset_version_id if source else None)
    session.add(report)
    await session.flush()
    await record_report_artifact(session, report)
    await audit(session, payload.workspace_id, actor.id, "report.copy" if source else "report.create", "report", report.id)
    await session.commit()
    await session.refresh(report)
    return as_report(report)


@router.patch("/api/v1/reports/{report_id}", response_model=ReportOut)
async def rename_report(report_id: str, payload: ReportRename, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    report, actor, _ = await report_and_actor(report_id, x_actor_id, session, "report.edit")
    title = payload.title.strip()
    if not title: raise HTTPException(422, "标题不能为空")
    session.add(ReportVersion(report_id=report.id, title=report.title, document=report.document))
    report.title = title
    report.document = {**report.document, "title": title}
    await record_report_artifact(session, report)
    await audit(session, report.workspace_id, actor.id, "report.rename", "report", report.id)
    await session.commit()
    await session.refresh(report)
    return as_report(report)


@router.delete("/api/v1/reports/{report_id}", status_code=204)
async def trash_report(report_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    report, actor, _ = await report_and_actor(report_id, x_actor_id, session, "report.edit", allow_deleted=True)
    if not report.deleted_at:
        report.deleted_at = datetime.now(timezone.utc)
        await audit(session, report.workspace_id, actor.id, "report.trash", "report", report.id)
        await session.commit()


@router.post("/api/v1/reports/{report_id}/restore", response_model=ReportOut)
async def untrash_report(report_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    report, actor, _ = await report_and_actor(report_id, x_actor_id, session, "report.edit", allow_deleted=True)
    report.deleted_at = None
    await audit(session, report.workspace_id, actor.id, "report.restore", "report", report.id)
    await session.commit()
    await session.refresh(report)
    return as_report(report)


@router.get("/api/v1/reports/{report_id}", response_model=ReportOut)
async def get_report(report_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    report, _, _ = await report_and_actor(report_id, x_actor_id, session, "report.view")
    return as_report(report)


@router.put("/api/v1/reports/{report_id}", response_model=ReportOut)
async def update_report(report_id: str, payload: ReportUpdate, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    report, _, _ = await report_and_actor(report_id, x_actor_id, session, "report.edit")
    payload.title = payload.title.strip()
    if not payload.title: raise HTTPException(422, "标题不能为空")
    session.add(ReportVersion(report_id=report.id, title=report.title, document=report.document))
    report.title = payload.title
    payload.document.title = payload.title
    # Client edits are drafts, never a new certificate for their own assertions.
    baseline = (report.document.get('metadata') or {}).get('claim_baseline')
    payload.document.metadata.pop('claim_baseline', None)
    if baseline: payload.document.metadata['claim_baseline'] = deepcopy(baseline)
    server_document = ReportDocument.model_validate(report.document)
    payload.document.evidence = server_document.evidence
    payload.document.claims = server_document.claims
    payload.document.quality = assess_report_quality(payload.document)
    report.document = payload.document.model_dump(mode="json")
    await record_report_artifact(session, report)
    await session.commit()
    await session.refresh(report)
    return as_report(report)


@router.get("/api/v1/reports/{report_id}/versions", response_model=list[ReportVersionOut])
async def list_report_versions(report_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    await report_and_actor(report_id, x_actor_id, session, "report.view")
    result = await session.scalars(
        select(ReportVersion).where(ReportVersion.report_id == report_id).order_by(ReportVersion.created_at.desc()).limit(50)
    )
    return [as_report_version(item) for item in result]


@router.get("/api/v1/reports/{report_id}/export.docx")
async def export_report_docx(report_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    report, _, _ = await report_and_actor(report_id, x_actor_id, session, "report.view")
    try:
        content = build_docx(report.title, report.document or {})
    except ValueError as exc:
        raise HTTPException(422, f"DOCX 导出失败：{exc}") from exc
    except Exception as exc:
        raise HTTPException(500, f"DOCX 导出失败：{exc}") from exc
    filename = quote(f"{report.title}.docx")
    return StreamingResponse(
        BytesIO(content), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.get("/api/v1/reports/{report_id}/quality", response_model=ReportQualityReport)
async def get_report_quality(report_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    report, _, _ = await report_and_actor(report_id, x_actor_id, session, "report.view")
    return assess_report_quality(report.document or {})


@router.post("/api/v1/reports/{report_id}/versions/{version_id}/restore", response_model=ReportOut)
async def restore_report_version(report_id: str, version_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    report, _, _ = await report_and_actor(report_id, x_actor_id, session, "report.edit")
    version = await session.get(ReportVersion, version_id)
    if not report or not version or version.report_id != report_id:
        raise HTTPException(404, "报告或历史版本不存在")
    session.add(ReportVersion(report_id=report.id, title=report.title, document=report.document))
    report.title = version.title
    report.document = version.document
    await record_report_artifact(session, report)
    await session.commit()
    await session.refresh(report)
    return as_report(report)
