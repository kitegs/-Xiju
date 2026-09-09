from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_session
from .models import Artifact, Conversation, Dataset, DatasetVersion, Evidence, Project, Report, Run, Workspace
from .schemas import (
    AnalysisBrief, AnalysisBriefUpdate, ArtifactRecordOut, BriefQuestionsRequest,
    DatasetVersionOut, EvidenceRecordOut, IntakeDecision, ProjectCreate, ProjectOut,
)
from .intake import apply_brief_update, evaluate_intake
from .services import storage_path


router = APIRouter(prefix="/api/v1")


def _project_out(item: Project) -> ProjectOut:
    return ProjectOut(
        id=item.id, workspace_id=item.workspace_id, name=item.name, description=item.description,
        scenario=item.scenario, status=item.status, is_default=item.is_default,
        analysis_brief=item.analysis_brief or {},
        created_at=item.created_at, updated_at=item.updated_at,
    )


def _dataset_version_out(item: DatasetVersion) -> DatasetVersionOut:
    return DatasetVersionOut(
        id=item.id, workspace_id=item.workspace_id, project_id=item.project_id,
        dataset_id=item.dataset_id, parent_version_id=item.parent_version_id,
        content_hash=item.content_hash, storage_format=item.storage_format,
        size_bytes=item.size_bytes, row_count=item.row_count,
        column_schema=item.schema_json or [], profile=item.profile or {}, created_at=item.created_at,
    )


def _artifact_out(item: Artifact) -> ArtifactRecordOut:
    return ArtifactRecordOut(
        id=item.id, workspace_id=item.workspace_id, project_id=item.project_id,
        run_id=item.run_id, report_id=item.report_id, legacy_artifact_id=item.legacy_artifact_id,
        kind=item.kind, name=item.name, version=item.version, content_uri=item.content_uri,
        content=item.content_json or {}, source_dataset_version_ids=item.source_dataset_version_ids or [],
        supersedes_artifact_id=item.supersedes_artifact_id, created_at=item.created_at,
    )


def _evidence_out(item: Evidence) -> EvidenceRecordOut:
    return EvidenceRecordOut(
        id=item.id, workspace_id=item.workspace_id, project_id=item.project_id,
        run_id=item.run_id, artifact_id=item.artifact_id, report_id=item.report_id,
        evidence_key=item.evidence_key, statement=item.statement, method=item.method,
        value=item.value, source_columns=item.source_columns or [], data=item.data or [],
        code=item.code, dataset_version_ids=item.dataset_version_ids or [], created_at=item.created_at,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def ensure_default_project(session: AsyncSession, workspace_id: str) -> Project:
    item = await session.scalar(
        select(Project).where(Project.workspace_id == workspace_id, Project.is_default.is_(True))
        .order_by(Project.created_at).limit(1)
    )
    if item:
        return item
    item = Project(
        workspace_id=workspace_id, name="默认分析项目",
        description="由兼容层为已有工作区建立，可在项目管理中修改。",
        scenario="general", is_default=True,
    )
    session.add(item)
    await session.flush()
    return item


async def ensure_dataset_version(
    session: AsyncSession, dataset: Dataset, *, parent_version_id: str | None = None,
    project_id: str | None = None,
) -> DatasetVersion:
    if dataset.current_version_id:
        current = await session.get(DatasetVersion, dataset.current_version_id)
        if current and (current.profile or {}).get("semantics", {}) == (dataset.semantics or {}):
            return current
        if current:
            parent_version_id = current.id
    if not dataset.project_id:
        project = await ensure_default_project(session, dataset.workspace_id)
        dataset.project_id = project_id or project.id
    path = storage_path(dataset.storage_key)
    if not path.is_file():
        raise FileNotFoundError(path)
    profile = {**(dataset.profile or {}), "semantics": dataset.semantics or {}}
    item = DatasetVersion(
        workspace_id=dataset.workspace_id, project_id=project_id or dataset.project_id,
        dataset_id=dataset.id, parent_version_id=parent_version_id,
        content_hash=_sha256(path), storage_key=dataset.storage_key,
        storage_format=path.suffix.lower().lstrip(".") or "unknown",
        size_bytes=dataset.size_bytes, row_count=int(profile.get("row_count") or 0),
        schema_json=profile.get("columns") or [], profile=profile,
    )
    session.add(item)
    await session.flush()
    dataset.current_version_id = item.id
    return item


async def report_source_versions(session: AsyncSession, report: Report) -> list[str]:
    """Resolve provenance from immutable version snapshots, never live metadata."""
    pending = [report.dataset_version_id] if report.dataset_version_id else []
    result = []
    while pending:
        version_id = pending.pop(0)
        if version_id in result:
            continue
        version = await session.get(DatasetVersion, version_id)
        if not version or version.workspace_id != report.workspace_id:
            continue
        result.append(version_id)
        pending.extend(((version.profile or {}).get("semantics") or {}).get("source_dataset_version_ids") or [])
    return result


async def persist_evidence(
    session: AsyncSession, *, report: Report, artifact: Artifact,
    run_id: str | None, records: list[dict] | None = None,
) -> list[Evidence]:
    records = records if records is not None else list((report.document or {}).get("evidence") or [])
    version_ids = await report_source_versions(session, report)
    saved: list[Evidence] = []
    for index, raw in enumerate(records):
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("id") or f"evidence-{index + 1}")[:160]
        existing = None
        if run_id:
            existing = await session.scalar(
                select(Evidence).where(Evidence.run_id == run_id, Evidence.evidence_key == key).limit(1)
            )
        if existing:
            saved.append(existing)
            continue
        item = Evidence(
            workspace_id=report.workspace_id, project_id=report.project_id,
            run_id=run_id, artifact_id=artifact.id, report_id=report.id,
            evidence_key=key, statement=str(raw.get("statement") or key),
            method=str(raw.get("method") or ""), value=str(raw.get("value") or ""),
            source_columns=list(raw.get("source_columns") or []),
            data=list(raw.get("data") or [])[:200], code=str(raw.get("code") or ""),
            dataset_version_ids=version_ids,
        )
        session.add(item)
        saved.append(item)
    await session.flush()
    return saved


async def record_report_artifact(
    session: AsyncSession, report: Report, *, run_id: str | None = None,
    evidence: list[dict] | None = None,
) -> Artifact:
    if not report.dataset_version_id and report.dataset_id:
        dataset = await session.get(Dataset, report.dataset_id)
        if dataset:
            version = await ensure_dataset_version(session, dataset)
            report.project_id = report.project_id or version.project_id
            report.dataset_version_id = version.id
    if not report.project_id:
        report.project_id = (await ensure_default_project(session, report.workspace_id)).id
    report.run_id = report.run_id or run_id
    if run_id:
        existing = await session.scalar(
            select(Artifact).where(
                Artifact.run_id == run_id, Artifact.report_id == report.id, Artifact.kind == "report",
            ).limit(1)
        )
        if existing:
            await persist_evidence(session, report=report, artifact=existing, run_id=run_id, records=evidence)
            return existing
    previous = await session.scalar(
        select(Artifact).where(Artifact.report_id == report.id, Artifact.kind == "report")
        .order_by(Artifact.version.desc()).limit(1)
    )
    item = Artifact(
        workspace_id=report.workspace_id, project_id=report.project_id,
        run_id=run_id, report_id=report.id, kind="report", name=report.title,
        version=(previous.version + 1) if previous else 1,
        content_uri=f"report://{report.id}", content_json=report.document or {},
        source_dataset_version_ids=await report_source_versions(session, report),
        supersedes_artifact_id=previous.id if previous else None,
    )
    session.add(item)
    await session.flush()
    await persist_evidence(session, report=report, artifact=item, run_id=run_id, records=evidence)
    return item


async def backfill_workspace(session: AsyncSession, workspace_id: str) -> Project:
    project = await ensure_default_project(session, workspace_id)
    datasets = (await session.scalars(select(Dataset).where(Dataset.workspace_id == workspace_id))).all()
    for dataset in datasets:
        dataset.project_id = dataset.project_id or project.id
        try:
            await ensure_dataset_version(session, dataset)
        except FileNotFoundError:
            # Keep old metadata visible even if a user has manually removed its source file.
            continue
    conversations = (await session.scalars(select(Conversation).where(Conversation.workspace_id == workspace_id))).all()
    for conversation in conversations:
        if not conversation.project_id:
            dataset = await session.get(Dataset, conversation.dataset_id) if conversation.dataset_id else None
            conversation.project_id = dataset.project_id if dataset and dataset.project_id else project.id
    reports = (await session.scalars(select(Report).where(Report.workspace_id == workspace_id))).all()
    for report in reports:
        if report.dataset_id and not report.dataset_version_id:
            dataset = await session.get(Dataset, report.dataset_id)
            if dataset and dataset.current_version_id:
                report.dataset_version_id = dataset.current_version_id
                report.project_id = report.project_id or dataset.project_id
        report.project_id = report.project_id or project.id
        existing = await session.scalar(select(Artifact.id).where(Artifact.report_id == report.id).limit(1))
        if not existing:
            await record_report_artifact(session, report, run_id=report.run_id)
    runs = (await session.scalars(select(Run).where(Run.workspace_id == workspace_id))).all()
    for run in runs:
        conversation = await session.get(Conversation, run.conversation_id)
        run.project_id = run.project_id or (conversation.project_id if conversation else None) or project.id
        if not run.dataset_version_ids and conversation and conversation.dataset_id:
            dataset = await session.get(Dataset, conversation.dataset_id)
            if dataset and dataset.current_version_id:
                run.dataset_version_ids = [dataset.current_version_id]
    await session.flush()
    return project


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(workspace_id: str, session: AsyncSession = Depends(get_session)):
    if not await session.get(Workspace, workspace_id):
        raise HTTPException(404, "工作区不存在")
    await backfill_workspace(session, workspace_id)
    await session.commit()
    result = await session.scalars(
        select(Project).where(Project.workspace_id == workspace_id).order_by(Project.is_default.desc(), Project.created_at)
    )
    return [_project_out(item) for item in result]


@router.post("/projects", response_model=ProjectOut, status_code=201)
async def create_project(payload: ProjectCreate, session: AsyncSession = Depends(get_session)):
    if not await session.get(Workspace, payload.workspace_id):
        raise HTTPException(404, "工作区不存在")
    item = Project(**payload.model_dump(), is_default=False)
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return _project_out(item)


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: str, session: AsyncSession = Depends(get_session)):
    item = await session.get(Project, project_id)
    if not item:
        raise HTTPException(404, "项目不存在")
    return _project_out(item)


async def _brief_context(
    session: AsyncSession,
    project_id: str,
    workspace_id: str,
    conversation_id: str | None,
    dataset_id: str | None,
) -> tuple[Project, Conversation | None, dict]:
    project = await session.get(Project, project_id)
    if not project or project.workspace_id != workspace_id:
        raise HTTPException(404, "项目不存在或不属于当前工作区")
    conversation = await session.get(Conversation, conversation_id) if conversation_id else None
    if conversation_id and (
        not conversation or conversation.workspace_id != workspace_id or conversation.project_id != project_id
    ):
        raise HTTPException(404, "会话不存在或不属于当前项目")
    resolved_dataset_id = dataset_id or (conversation.dataset_id if conversation else None)
    dataset = await session.get(Dataset, resolved_dataset_id) if resolved_dataset_id else None
    if resolved_dataset_id and (
        not dataset or dataset.workspace_id != workspace_id or dataset.project_id != project_id
    ):
        raise HTTPException(404, "数据集不存在或不属于当前项目")
    return project, conversation, (dataset.profile or {}) if dataset else {}


@router.get("/projects/{project_id}/brief", response_model=AnalysisBrief)
async def get_analysis_brief(project_id: str, workspace_id: str, session: AsyncSession = Depends(get_session)):
    project, _, _ = await _brief_context(session, project_id, workspace_id, None, None)
    return AnalysisBrief.model_validate(project.analysis_brief or {})


@router.post("/projects/{project_id}/brief/questions", response_model=IntakeDecision)
async def get_brief_questions(
    project_id: str, payload: BriefQuestionsRequest, session: AsyncSession = Depends(get_session),
):
    project, conversation, profile = await _brief_context(
        session, project_id, payload.workspace_id, payload.conversation_id, payload.dataset_id,
    )
    brief = AnalysisBrief.model_validate(project.analysis_brief or {})
    mode = payload.mode or (conversation.clarification_mode if conversation else "auto")
    decision = evaluate_intake(payload.objective, profile, brief, mode)
    if decision.questions:
        recorded = apply_brief_update(
            brief,
            AnalysisBriefUpdate(workspace_id=payload.workspace_id, objective=payload.objective),
            decision,
        )
        project.analysis_brief = recorded.model_dump(mode="json")
        await session.commit()
    return decision


@router.put("/projects/{project_id}/brief", response_model=AnalysisBrief)
async def update_analysis_brief(
    project_id: str, payload: AnalysisBriefUpdate, session: AsyncSession = Depends(get_session),
):
    project, _, profile = await _brief_context(
        session, project_id, payload.workspace_id, payload.conversation_id, payload.dataset_id,
    )
    brief = AnalysisBrief.model_validate(project.analysis_brief or {})
    objective = payload.objective or brief.request_summary or "生成报告"
    decision = evaluate_intake(objective, profile, brief, "always")
    updated = apply_brief_update(brief, payload, decision)
    project.analysis_brief = updated.model_dump(mode="json")
    await session.commit()
    return updated


@router.get("/projects/{project_id}/dataset-versions", response_model=list[DatasetVersionOut])
async def list_dataset_versions(project_id: str, session: AsyncSession = Depends(get_session)):
    if not await session.get(Project, project_id):
        raise HTTPException(404, "项目不存在")
    result = await session.scalars(
        select(DatasetVersion).where(DatasetVersion.project_id == project_id).order_by(DatasetVersion.created_at.desc())
    )
    return [_dataset_version_out(item) for item in result]


@router.get("/dataset-versions/{version_id}", response_model=DatasetVersionOut)
async def get_dataset_version(version_id: str, session: AsyncSession = Depends(get_session)):
    item = await session.get(DatasetVersion, version_id)
    if not item:
        raise HTTPException(404, "数据版本不存在")
    return _dataset_version_out(item)


@router.get("/projects/{project_id}/artifacts", response_model=list[ArtifactRecordOut])
async def list_project_artifacts(project_id: str, session: AsyncSession = Depends(get_session)):
    if not await session.get(Project, project_id):
        raise HTTPException(404, "项目不存在")
    result = await session.scalars(
        select(Artifact).where(Artifact.project_id == project_id).order_by(Artifact.created_at.desc())
    )
    return [_artifact_out(item) for item in result]


@router.get("/projects/{project_id}/runs")
async def list_project_runs(project_id: str, session: AsyncSession = Depends(get_session)):
    if not await session.get(Project, project_id):
        raise HTTPException(404, "项目不存在")
    result = await session.scalars(select(Run).where(Run.project_id == project_id).order_by(Run.created_at.desc()))
    return [{
        "id": item.id, "status": item.status, "attempt": item.attempt,
        "dataset_version_ids": item.dataset_version_ids or [], "analysis_spec": item.analysis_spec or {},
        "report_id": item.report_id, "created_at": item.created_at,
    } for item in result]


@router.get("/runs/{run_id}/evidence", response_model=list[EvidenceRecordOut])
async def list_run_evidence(run_id: str, session: AsyncSession = Depends(get_session)):
    if not await session.get(Run, run_id):
        raise HTTPException(404, "运行记录不存在")
    result = await session.scalars(select(Evidence).where(Evidence.run_id == run_id).order_by(Evidence.created_at))
    return [_evidence_out(item) for item in result]
