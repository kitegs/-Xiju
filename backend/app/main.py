from __future__ import annotations

import json
from copy import deepcopy
import re
import shutil
import time
import asyncio
from io import BytesIO
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlparse
from uuid import uuid4

import pandas as pd
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .config import (
    ALLOWED_EXTENSIONS, CURATED_DATABASE_URL, DAILY_LLM_BUDGET_CNY, DATA_DIR, MAX_UPLOAD_BYTES,
    SAMPLE_DIR, SANDBOX_ENABLED, SANDBOX_IMAGE, SUPERSET_URL,
)
from .analysis_modes import (
    ANALYSIS_MODES, cleaning_recommendations, describe_statistics, mode_catalog, resolve_mode, survey_statistics,
)
from .research import inferential_statistics, survey_cross_analysis
from .forecasting import forecast_time_series, recommendation_actions
from .external_bi import (
    create_embedded_dashboard, integration_status, normalize_embedded_domains,
    publish_superset_dashboard, repair_embedded_dashboard, superset_guest_token,
)
from .database import Base, SessionLocal, engine, ensure_compat_schema, get_session
from .llm import complete, test_provider
from .capabilities import COMPONENT_TOOLS, attach_deep_analysis, configure_steps, deepen, optimize_layout, review as review_content, alternatives as report_alternatives
from .exporting import build_docx
from .models import AnalysisRun, AppSetting, ChatMessage, CleaningRecipe, Conversation, Dataset, DatasetRelationship, ExternalResource, GeneratedArtifact, LlmUsageLog, McpServer, Project, ProviderConfig, Report, ReportTemplate, ReportVersion, RunEvent, Workspace
from .policy import ToolPolicyError, enforce_tools, evaluate_tools
from .prompting import (
    PROMPT_VERSIONS, fallback_synthesis, planning_context, planner_prompt, render_synthesis,
    synthesis_context, synthesis_prompt, validate_synthesis,
)
from .report_templates import MAX_TEMPLATE_BYTES, UnsafeTemplate, inspect_docx_template, render_docx_template
from .schemas import (
    AnalysisBrief, AnalysisBriefUpdate, AnalysisOptions, AnalysisRequest, AnalysisResult, AppSettingsOut, AppSettingsUpdate, ChartPreviewRequest,
    AnalysisPlan, AnalysisPlanStep, ChartPreviewResult, ChartSpec, ChartContextOut, ChartPatchApplyRequest, ChartPatchPreviewOut, ChartProposalAlternative,
    ChartPatchPreviewRequest, ChartProposalOut, ChartProposalRequest, ChatExecuteRequest, ChatMessageOut, ChatPlanRequest, ChatPlanResult,
    CleaningApplyOut, CleaningApplyRequest, CleaningPreviewOut, CleaningPreviewRequest, CleaningRecipeOut, CleaningStep,
    ChatRequest, ChatResult, ConversationCreate, ConversationOut, ConversationUpdate,
    DatasetOut, DatasetPreviewOut, DatasetRelationshipOut, DatasetSemanticsUpdate, McpServerCreate, McpServerOut, McpServerTestOut, McpServerUpdate, ProviderConfigOut, ProviderConfigUpdate, ProviderTestResult, RelationshipApplyRequest, RelationshipPreviewRequest, RelationshipProfile, ReportOut,
    ReportBlock, ReportDocument, ReportQualityReport, ReportUpdate, ReportVersionOut, ReportLayoutRequest, ReportLayoutProposal, ReportLayoutProposalOut, ReportLayoutApplyRequest, SqlRunRequest, SqlRunOut, PythonRunRequest, PythonRunOut, WorkspaceCreate, WorkspaceOut,
    SupersetPublishPreviewRequest, SupersetPublishRequest, SupersetPublishResult,
    AnalysisRunOut, ArtifactOut, ForecastOut, ForecastRequest, ReportTemplateOut, RunEventOut, TemplateRenderRequest, ToolPolicyDecision,
    TokenUsageSummary,
)
from .sandbox import SandboxUnavailable, run_generated_python, run_generated_python_async
from .secrets import decrypt_secret, encrypt_secret, mask_secret
from .mcp_client import call_tool as call_mcp_tool, list_tools as list_mcp_tools
from .services import analysis_context, apply_cleaning_steps, assess_report_quality, build_report, dataframe_rows, new_storage_key, normalize_sql_columns, profile_dataframe, quality_summary, read_dataframe, run_sql_query, storage_path, validate_non_additive_sql
from .charting import apply_chart_patch as apply_chart_spec_patch, apply_computed_chart, chart_by_id, chart_version_hint, compute_chart_data, quality_report
from .team import ROLE_PERMISSIONS, actor_for, audit, ensure_owner, report_and_actor, require, router as team_router
from .commercial import backfill_workspace, ensure_dataset_version, record_report_artifact, router as commercial_router
from .usage import summarize_token_usage
from .intake import apply_brief_to_report, apply_brief_update, evaluate_intake
from .schemas import ReportCreate, ReportRename, Evidence
from .report_claims import seal_chart, seal_claims
from .report_repair import router as report_repair_router
from .relationships import RelationshipValidationError, materialize_relationship, profile_relationship, inherit_relationship_restrictions, cleaning_semantics
from .report_catalog import router as report_catalog_router
from .report_routes import router as report_router
from .presenters import as_report, as_report_version, as_artifact, as_message
from .run_execution import execute_plan, ExecutionPorts
from .run_runtime import RunCancelled, run_background
from .prompting import parse_json_object as _extract_json_object
from .domain import transition_run, reserved_capabilities


PROVIDER_DEFAULTS = {
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-5.6-terra", "options": {"reasoning_effort": "medium"}},
    "deepseek": {"base_url": "https://api.deepseek.com", "model": "deepseek-v4-flash", "options": {"temperature": 0.2, "thinking": {"type": "disabled"}}},
}
DEFAULT_APP_SETTINGS = {
    "language": "zh-CN", "theme": "light", "autosave": True, "autosave_interval_seconds": 30,
    "safe_mode": True, "autonomy_mode": "balanced", "telemetry": False, "default_export": "pdf", "confirm_external_requests": True,
    "default_clarification_mode": "auto",
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(ensure_compat_schema)
    await _recover_local_runs()
    yield


app = FastAPI(title="AI BI V2", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_origin_regex=r"http://(?:localhost|127\.0\.0\.1):51\d{2}",
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)
app.include_router(team_router)
app.include_router(commercial_router)
app.include_router(report_repair_router)
app.include_router(report_catalog_router)
app.include_router(report_router)


LOCAL_TASKS: dict[str, asyncio.Task] = {}
RUN_EVENT_LOCKS: dict[str, asyncio.Lock] = {}
RUN_EVENT_SEQUENCES: dict[str, int] = {}


def _apply_plan_policy(plan: AnalysisPlan) -> AnalysisPlan:
    decisions = evaluate_tools(plan.execution_mode, [step.tool for step in plan.steps])
    plan.policy = [ToolPolicyDecision.model_validate(decision.as_dict()) for decision in decisions]
    plan.blocked = any(decision.decision == "forbid" for decision in decisions)
    plan.requires_approval = plan.blocked or any(decision.decision == "approval" for decision in decisions)
    return plan


async def _append_run_event(
    session: AsyncSession, run_id: str, event_type: str, status: str, message: str,
    *, step_id: str | None = None, data: dict | None = None,
) -> RunEvent:
    async with RUN_EVENT_LOCKS.setdefault(run_id, asyncio.Lock()):
        last_sequence = RUN_EVENT_SEQUENCES.get(run_id)
        if last_sequence is None:
            last_sequence = int(await session.scalar(select(func.max(RunEvent.sequence)).where(RunEvent.run_id == run_id)) or 0)
        sequence = last_sequence + 1
        RUN_EVENT_SEQUENCES[run_id] = sequence
        event = RunEvent(
            run_id=run_id, sequence=sequence, event_type=event_type,
            step_id=step_id, status=status, message=message[:1000], data=data or {},
        )
        session.add(event)
        await session.flush()
        return event


def _schedule_run(run_id: str, actor_id: str | None = None) -> None:
    existing = LOCAL_TASKS.get(run_id)
    if existing and not existing.done():
        return
    LOCAL_TASKS[run_id] = asyncio.create_task(_run_analysis_task(run_id, actor_id))


async def _recover_local_runs() -> None:
    async with SessionLocal() as session:
        interrupted = (await session.scalars(select(AnalysisRun).where(AnalysisRun.status == "running"))).all()
        for run in interrupted:
            transition_run(run, "interrupted")
            run.error = "应用异常退出；运行已标记为 interrupted，可从运行历史重试。"
            run.finished_at = datetime.now(timezone.utc)
            await _append_run_event(session, run.id, "interrupted", "interrupted", run.error)
        queued_ids = list((await session.scalars(select(AnalysisRun.id).where(AnalysisRun.status == "queued"))).all())
        await session.commit()
    for run_id in queued_ids:
        _schedule_run(run_id)


def as_workspace(item: Workspace) -> WorkspaceOut:
    return WorkspaceOut(id=item.id, name=item.name, description=item.description, created_at=item.created_at)


def as_dataset(item: Dataset) -> DatasetOut:
    return DatasetOut(
        id=item.id, workspace_id=item.workspace_id, project_id=item.project_id,
        current_version_id=item.current_version_id, name=item.name, original_name=item.original_name,
        size_bytes=item.size_bytes, profile=item.profile or {}, semantics=item.semantics or {}, created_at=item.created_at,
    )


async def as_relationship(session: AsyncSession, item: DatasetRelationship) -> DatasetRelationshipOut:
    result_dataset = await session.get(Dataset, item.result_dataset_id) if item.result_dataset_id else None
    return DatasetRelationshipOut(
        id=item.id, workspace_id=item.workspace_id, project_id=item.project_id, name=item.name,
        left_dataset_id=item.left_dataset_id, right_dataset_id=item.right_dataset_id,
        left_version_id=item.left_version_id, right_version_id=item.right_version_id,
        left_keys=item.left_keys or [], right_keys=item.right_keys or [], join_type=item.join_type,
        cardinality=item.cardinality, right_prefix=item.right_prefix,
        profile=RelationshipProfile.model_validate(item.profile or {}),
        result_dataset_id=item.result_dataset_id,
        result_dataset=as_dataset(result_dataset) if result_dataset else None,
        created_at=item.created_at,
    )


def as_recipe(item: CleaningRecipe) -> CleaningRecipeOut:
    return CleaningRecipeOut(
        id=item.id, workspace_id=item.workspace_id, source_dataset_id=item.source_dataset_id,
        result_dataset_id=item.result_dataset_id, source_version_id=item.source_version_id,
        result_version_id=item.result_version_id, name=item.name, steps=item.steps or [],
        impact=item.impact or {}, created_at=item.created_at,
    )


def as_analysis_run(item: AnalysisRun) -> AnalysisRunOut:
    return AnalysisRunOut(
        id=item.id, workspace_id=item.workspace_id, project_id=item.project_id,
        conversation_id=item.conversation_id,
        plan_message_id=item.plan_message_id, status=item.status, attempt=item.attempt,
        idempotency_key=item.idempotency_key, approval_granted=item.approval_granted,
        cancel_requested=item.cancel_requested, result_message_id=item.result_message_id,
        report_id=item.report_id, error=item.error, progress=item.progress or {},
        dataset_version_ids=item.dataset_version_ids or [], analysis_spec=item.analysis_spec or {},
        started_at=item.started_at, finished_at=item.finished_at, created_at=item.created_at,
    )


def as_run_event(item: RunEvent) -> RunEventOut:
    return RunEventOut(
        id=item.id, run_id=item.run_id, sequence=item.sequence, event_type=item.event_type,
        step_id=item.step_id, status=item.status, message=item.message, data=item.data or {},
        created_at=item.created_at,
    )


def as_template(item: ReportTemplate) -> ReportTemplateOut:
    return ReportTemplateOut(
        id=item.id, workspace_id=item.workspace_id, name=item.name, original_name=item.original_name,
        size_bytes=item.size_bytes, placeholders=item.placeholders or [], metadata=item.metadata_json or {},
        created_at=item.created_at,
    )


def as_conversation(item: Conversation) -> ConversationOut:
    return ConversationOut(
        id=item.id, workspace_id=item.workspace_id, project_id=item.project_id,
        dataset_id=item.dataset_id, title=item.title, archived=item.archived,
        clarification_mode=item.clarification_mode or "auto",
        analysis_capabilities=item.analysis_capabilities or {},
        created_at=item.created_at, updated_at=item.updated_at,
    )


def as_message_for_permissions(item: ChatMessage, permissions: list[str]) -> ChatMessageOut:
    output = as_message(item)
    if "code.view" in permissions:
        return output
    meta = json.loads(json.dumps(output.message_meta, ensure_ascii=False, default=str))
    for evidence in meta.get("evidence", []):
        evidence.pop("code", None)
    for run in meta.get("tool_runs", []):
        run.pop("code", None)
        run.pop("logs", None)
        if run.get("tool") in {"sql.query", "python.run"}:
            run["input_summary"] = "代码已按当前角色权限隐藏"
    output.message_meta = meta
    return output


async def daily_llm_spend(session: AsyncSession, workspace_id: str) -> float:
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    value = await session.scalar(
        select(func.coalesce(func.sum(LlmUsageLog.estimated_cost_cny), 0.0)).where(
            LlmUsageLog.workspace_id == workspace_id,
            LlmUsageLog.status == "completed",
            LlmUsageLog.created_at >= day_start,
        )
    )
    return float(value or 0.0)


async def enforce_llm_budget(session: AsyncSession, workspace_id: str) -> float:
    spent = await daily_llm_spend(session, workspace_id)
    if spent >= DAILY_LLM_BUDGET_CNY:
        raise HTTPException(402, f"今日模型预算已用完（¥{spent:.4f} / ¥{DAILY_LLM_BUDGET_CNY:.2f}）")
    return spent


def usage_log(
    workspace_id: str,
    conversation_id: str | None,
    plan_id: str | None,
    provider: ProviderConfig,
    result,
    *,
    stage: Literal["intake", "planning", "synthesis", "chart", "report", "dashboard"],
    purpose: str,
    run_id: str | None = None,
    report_id: str | None = None,
    dashboard_id: str | None = None,
) -> LlmUsageLog:
    meta = result.as_meta()
    return LlmUsageLog(
        workspace_id=workspace_id, conversation_id=conversation_id, plan_id=plan_id,
        stage=stage, run_id=run_id, report_id=report_id, dashboard_id=dashboard_id,
        purpose=purpose[:120], usage_unavailable=not bool(meta.get("usage_available", True)),
        provider=provider.provider, model=meta["model"], request_id=meta["request_id"],
        prompt_tokens=meta["prompt_tokens"], cache_hit_tokens=meta["cache_hit_tokens"],
        cache_miss_tokens=meta["cache_miss_tokens"], completion_tokens=meta["completion_tokens"],
        total_tokens=meta["total_tokens"], estimated_cost_cny=meta["estimated_cost_cny"],
        latency_ms=meta["latency_ms"], status="completed", pricing=meta["pricing"],
    )


def as_provider(item: ProviderConfig | None, provider: str) -> ProviderConfigOut:
    defaults = PROVIDER_DEFAULTS[provider]
    secret = decrypt_secret(item.encrypted_api_key) if item and item.encrypted_api_key else ""
    return ProviderConfigOut(
        provider=provider, enabled=item.enabled if item else False, is_default=item.is_default if item else provider == "openai",
        base_url=item.base_url if item else defaults["base_url"], model=item.model if item else defaults["model"],
        has_api_key=bool(secret), masked_api_key=mask_secret(secret), options=item.options if item else defaults["options"],
        updated_at=item.updated_at if item else None,
    )


def as_mcp_server(item: McpServer) -> McpServerOut:
    secret = decrypt_secret(item.encrypted_bearer_token) if item.encrypted_bearer_token else ""
    return McpServerOut(
        id=item.id, workspace_id=item.workspace_id, name=item.name, url=item.url,
        transport=item.transport, enabled=item.enabled, tool_allowlist=item.tool_allowlist or [],
        tool_cache=item.tool_cache or {}, has_bearer_token=bool(secret), masked_bearer_token=mask_secret(secret),
        last_checked_at=item.last_checked_at, updated_at=item.updated_at,
    )


def validate_provider_url(value: str) -> str:
    parsed = urlparse(value)
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme == "https" and parsed.netloc:
        return value.rstrip("/")
    if parsed.scheme == "http" and parsed.hostname in local_hosts:
        return value.rstrip("/")
    raise HTTPException(400, "API 地址必须使用 HTTPS；仅本机 localhost 可使用 HTTP")


@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "service": "ai-bi-v2"}


@app.get("/api/v1/workspaces", response_model=list[WorkspaceOut])
async def list_workspaces(session: AsyncSession = Depends(get_session)):
    result = await session.scalars(select(Workspace).order_by(Workspace.created_at.desc()))
    return [as_workspace(item) for item in result]


@app.post("/api/v1/workspaces", response_model=WorkspaceOut, status_code=201)
async def create_workspace(payload: WorkspaceCreate, session: AsyncSession = Depends(get_session)):
    item = Workspace(**payload.model_dump())
    session.add(item)
    await session.flush()
    await backfill_workspace(session, item.id)
    await ensure_owner(session, item.id)
    await session.commit()
    await session.refresh(item)
    return as_workspace(item)


@app.post("/api/v1/workspaces/bootstrap", response_model=WorkspaceOut)
async def bootstrap_workspace(session: AsyncSession = Depends(get_session)):
    existing = await session.scalar(select(Workspace).order_by(Workspace.created_at).limit(1))
    if existing:
        await backfill_workspace(session, existing.id)
        await ensure_owner(session, existing.id)
        await session.commit()
        await session.refresh(existing)
        return as_workspace(existing)
    item = Workspace(name="我的分析工作区", description="本地专业编辑与团队协作演示工作区")
    session.add(item)
    await session.flush()
    await backfill_workspace(session, item.id)
    await ensure_owner(session, item.id)
    await session.commit()
    await session.refresh(item)
    return as_workspace(item)


@app.get("/api/v1/datasets", response_model=list[DatasetOut])
async def list_datasets(workspace_id: str, session: AsyncSession = Depends(get_session)):
    await backfill_workspace(session, workspace_id)
    await session.commit()
    result = await session.scalars(select(Dataset).where(Dataset.workspace_id == workspace_id).order_by(Dataset.created_at.desc()))
    return [as_dataset(item) for item in result]


@app.get("/api/v1/datasets/{dataset_id}/preview", response_model=DatasetPreviewOut)
async def preview_dataset(dataset_id: str, workspace_id: str, offset: int = 0, limit: int = 50, session: AsyncSession = Depends(get_session)):
    if offset < 0 or limit < 1 or limit > 200:
        raise HTTPException(400, "预览范围无效")
    dataset = await session.get(Dataset, dataset_id)
    if not dataset or dataset.workspace_id != workspace_id:
        raise HTTPException(404, "数据集不存在或不属于当前工作区")
    try:
        frame = read_dataframe(dataset.storage_key)
    except Exception as exc:
        raise HTTPException(400, f"无法读取数据集：{exc}") from exc
    fresh_profile = profile_dataframe(frame)
    if dataset.profile != fresh_profile:
        dataset.profile = fresh_profile
        await session.commit()
        await session.refresh(dataset)
    return DatasetPreviewOut(
        dataset=as_dataset(dataset), columns=[str(column) for column in frame.columns],
        rows=dataframe_rows(frame, limit=limit, offset=offset), offset=offset, limit=limit,
        total_rows=len(frame), quality=quality_summary(frame),
    )


@app.patch("/api/v1/datasets/{dataset_id}/semantics", response_model=DatasetOut)
async def update_dataset_semantics(
    dataset_id: str, payload: DatasetSemanticsUpdate, session: AsyncSession = Depends(get_session),
):
    dataset = await session.get(Dataset, dataset_id)
    if not dataset or dataset.workspace_id != payload.workspace_id:
        raise HTTPException(404, "数据集不存在或不属于当前工作区")
    frame = read_dataframe(dataset.storage_key)
    columns = {str(column) for column in frame.columns}
    referenced = set(payload.date_formats) | set(payload.column_roles) | set(payload.column_units) | set(payload.column_labels) | set(payload.value_labels)
    unknown = sorted(referenced - columns)
    if unknown:
        raise HTTPException(400, "语义设置引用了不存在的字段：" + "、".join(unknown))
    for column, date_format in payload.date_formats.items():
        try:
            parsed = pd.to_datetime(frame[column], errors="coerce", format=date_format or "mixed")
        except Exception as exc:
            raise HTTPException(400, f"字段“{column}”的日期格式无效：{exc}") from exc
        if parsed.notna().mean() < .8:
            raise HTTPException(400, f"字段“{column}”按格式“{date_format}”解析成功率低于 80%")
    protected = {
        key: value for key, value in (dataset.semantics or {}).items()
        if key in {"grain", "relationship_id", "cardinality", "left_keys", "right_keys", "source_dataset_ids", "source_dataset_version_ids", "field_lineage", "non_additive_columns", "warnings"}
    }
    dataset.semantics = {
        **protected, "unit": payload.unit.strip(), "currency": payload.currency.strip(),
        "grain": payload.grain.strip() or protected.get("grain", ""),
        "date_formats": payload.date_formats, "column_roles": payload.column_roles,
        "column_units": payload.column_units, "column_labels": payload.column_labels,
        "value_labels": payload.value_labels,
    }
    await ensure_dataset_version(session, dataset)
    await session.commit()
    await session.refresh(dataset)
    return as_dataset(dataset)


@app.post("/api/v1/datasets/{dataset_id}/cleaning/preview", response_model=CleaningPreviewOut)
async def preview_cleaning(dataset_id: str, payload: CleaningPreviewRequest, session: AsyncSession = Depends(get_session)):
    dataset = await session.get(Dataset, dataset_id)
    if not dataset or dataset.workspace_id != payload.workspace_id:
        raise HTTPException(404, "数据集不存在或不属于当前工作区")
    try:
        source = read_dataframe(dataset.storage_key)
        result, step_results, changed_cells = apply_cleaning_steps(source, payload.steps)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, f"清洗预览失败：{exc}") from exc
    return CleaningPreviewOut(
        source_dataset_id=dataset.id, before_rows=len(source), after_rows=len(result),
        removed_rows=len(source) - len(result), changed_cells=changed_cells,
        columns=[str(column) for column in result.columns], rows=dataframe_rows(result, payload.sample_limit),
        profile=profile_dataframe(result), quality=quality_summary(result), step_results=step_results,
    )


async def _create_cleaned_copy(
    session: AsyncSession, dataset: Dataset, workspace_id: str, name: str | None, steps: list[CleaningStep],
) -> tuple[Dataset, CleaningRecipe, pd.DataFrame, dict]:
    target = None
    try:
        source_version = await ensure_dataset_version(session, dataset)
        source = read_dataframe(dataset.storage_key)
        result, step_results, changed_cells = apply_cleaning_steps(source, steps)
        storage_key = new_storage_key(workspace_id, ".csv")
        target = storage_path(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(target, index=False, encoding="utf-8-sig")
        result_name = (name or f"{dataset.name} · 已清洗").strip()
        result_dataset = Dataset(
            workspace_id=workspace_id, name=result_name, original_name=f"{result_name}.csv",
            storage_key=storage_key, size_bytes=target.stat().st_size, profile=profile_dataframe(result),
            semantics=cleaning_semantics(dataset.semantics, steps, list(result.columns)),
        )
        session.add(result_dataset)
        await session.flush()
        result_version = await ensure_dataset_version(
            session, result_dataset, parent_version_id=source_version.id, project_id=source_version.project_id,
        )
        impact = {
            "before_rows": len(source), "after_rows": len(result), "removed_rows": len(source) - len(result),
            "changed_cells": changed_cells, "step_results": step_results,
        }
        recipe = CleaningRecipe(
            workspace_id=workspace_id, source_dataset_id=dataset.id, result_dataset_id=result_dataset.id,
            source_version_id=source_version.id, result_version_id=result_version.id,
            name=f"{dataset.name} 清洗配方", steps=[step.model_dump(mode="json") for step in steps], impact=impact,
        )
        session.add(recipe)
        await session.flush()
        return result_dataset, recipe, result, impact
    except Exception:
        if target:
            target.unlink(missing_ok=True)
        raise


@app.post("/api/v1/datasets/{dataset_id}/cleaning/apply", response_model=CleaningApplyOut, status_code=201)
async def apply_cleaning(dataset_id: str, payload: CleaningApplyRequest, session: AsyncSession = Depends(get_session)):
    dataset = await session.get(Dataset, dataset_id)
    if not dataset or dataset.workspace_id != payload.workspace_id:
        raise HTTPException(404, "数据集不存在或不属于当前工作区")
    result_dataset = None
    try:
        result_dataset, recipe, _, _ = await _create_cleaned_copy(
            session, dataset, payload.workspace_id, payload.name, payload.steps,
        )
        await session.commit()
        await session.refresh(result_dataset)
        await session.refresh(recipe)
    except ValueError as exc:
        if result_dataset:
            storage_path(result_dataset.storage_key).unlink(missing_ok=True)
        await session.rollback()
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        if result_dataset:
            storage_path(result_dataset.storage_key).unlink(missing_ok=True)
        await session.rollback()
        raise HTTPException(400, f"执行清洗失败：{exc}") from exc
    return CleaningApplyOut(dataset=as_dataset(result_dataset), recipe=as_recipe(recipe))


@app.get("/api/v1/cleaning-recipes", response_model=list[CleaningRecipeOut])
async def list_cleaning_recipes(workspace_id: str, dataset_id: str | None = None, session: AsyncSession = Depends(get_session)):
    query = select(CleaningRecipe).where(CleaningRecipe.workspace_id == workspace_id)
    if dataset_id:
        query = query.where(CleaningRecipe.source_dataset_id == dataset_id)
    result = await session.scalars(query.order_by(CleaningRecipe.created_at.desc()))
    return [as_recipe(item) for item in result]


@app.post("/api/v1/datasets/upload", response_model=DatasetOut, status_code=201)
async def upload_dataset(workspace_id: str = Form(...), file: UploadFile = File(...), session: AsyncSession = Depends(get_session)):
    workspace = await session.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(404, "工作区不存在")
    original_name = Path(file.filename or "dataset").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, "仅支持 CSV、XLSX、XLS 文件")
    storage_key = new_storage_key(workspace_id, suffix)
    target = storage_path(storage_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    try:
        with target.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"文件不能超过 {MAX_UPLOAD_BYTES // 1024 // 1024}MB")
                output.write(chunk)
        frame = read_dataframe(storage_key)
        profile = profile_dataframe(frame)
    except HTTPException:
        target.unlink(missing_ok=True)
        raise
    except Exception as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(400, f"无法解析数据文件：{exc}") from exc
    finally:
        await file.close()
    item = Dataset(workspace_id=workspace_id, name=Path(original_name).stem, original_name=original_name, storage_key=storage_key, size_bytes=size, profile=profile)
    session.add(item)
    await session.flush()
    await ensure_dataset_version(session, item)
    await session.commit()
    await session.refresh(item)
    return as_dataset(item)


async def _relationship_datasets(
    session: AsyncSession, workspace_id: str, left_dataset_id: str, right_dataset_id: str,
) -> tuple[Dataset, Dataset]:
    if left_dataset_id == right_dataset_id:
        raise HTTPException(400, "请选择两个不同的数据集")
    left = await session.get(Dataset, left_dataset_id)
    right = await session.get(Dataset, right_dataset_id)
    if not left or not right or left.workspace_id != workspace_id or right.workspace_id != workspace_id:
        raise HTTPException(404, "关联数据集不存在或不属于当前工作区")
    return left, right


@app.post("/api/v1/dataset-relationships/preview", response_model=RelationshipProfile)
async def preview_dataset_relationship(payload: RelationshipPreviewRequest, session: AsyncSession = Depends(get_session)):
    left, right = await _relationship_datasets(
        session, payload.workspace_id, payload.left_dataset_id, payload.right_dataset_id,
    )
    try:
        profile = profile_relationship(
            read_dataframe(left.storage_key), read_dataframe(right.storage_key),
            payload.left_keys, payload.right_keys, payload.join_type, payload.right_prefix,
        )
        inherit_relationship_restrictions(profile, left.semantics, right.semantics)
        return RelationshipProfile.model_validate(profile)
    except RelationshipValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, f"关联预览失败：{exc}") from exc


@app.post("/api/v1/dataset-relationships", response_model=DatasetRelationshipOut, status_code=201)
async def create_dataset_relationship(payload: RelationshipApplyRequest, session: AsyncSession = Depends(get_session)):
    left, right = await _relationship_datasets(
        session, payload.workspace_id, payload.left_dataset_id, payload.right_dataset_id,
    )
    target: Path | None = None
    try:
        left_version = await ensure_dataset_version(session, left)
        right_version = await ensure_dataset_version(session, right)
        result, profile, field_lineage = materialize_relationship(
            read_dataframe(left.storage_key), read_dataframe(right.storage_key),
            payload.left_keys, payload.right_keys, payload.join_type, payload.right_prefix,
        )
        inherit_relationship_restrictions(profile, left.semantics, right.semantics)
        for name, lineage in field_lineage.items():
            lineage["additive"] = name not in profile["non_additive_columns"]
            source = left if lineage["source_side"] == "left" else right
            lineage["source_dataset_id"] = source.id
            lineage["source_dataset_version_id"] = left_version.id if source is left else right_version.id
            previous = (source.semantics or {}).get("field_lineage", {}).get(lineage["source_column"])
            if previous:
                lineage["upstream"] = previous
        if profile["non_additive_columns"] and not payload.acknowledge_non_additive:
            raise RelationshipValidationError(
                "右表数值字段在 N:1 连接后不可求和；请确认已理解重复累计风险后再生成副本"
            )
        relation = DatasetRelationship(
            workspace_id=payload.workspace_id, project_id=left_version.project_id, name=payload.name.strip(),
            left_dataset_id=left.id, right_dataset_id=right.id,
            left_version_id=left_version.id, right_version_id=right_version.id,
            left_keys=payload.left_keys, right_keys=payload.right_keys,
            join_type=payload.join_type, cardinality=profile["cardinality"],
            right_prefix=profile["right_prefix"], profile=profile,
        )
        session.add(relation)
        await session.flush()

        storage_key = new_storage_key(payload.workspace_id, ".csv")
        target = storage_path(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(target, index=False, encoding="utf-8-sig")
        source_version_ids = [left_version.id, right_version.id]
        semantics = {
            **(left.semantics or {}),
            "grain": "左表明细粒度",
            "relationship_id": relation.id,
            "cardinality": profile["cardinality"],
            "left_keys": profile["left_keys"], "right_keys": profile["right_keys"],
            "source_dataset_ids": [left.id, right.id],
            "source_dataset_version_ids": source_version_ids,
            "field_lineage": field_lineage,
            "non_additive_columns": profile["non_additive_columns"],
            "warnings": profile["warnings"],
        }
        result_profile = profile_dataframe(result)
        result_profile["relationship"] = {
            "id": relation.id, "name": relation.name, "grain": semantics["grain"],
            "cardinality": profile["cardinality"], "match_rate": profile["match_rate"],
            "source_dataset_version_ids": source_version_ids,
            "non_additive_columns": profile["non_additive_columns"],
        }
        result_dataset = Dataset(
            workspace_id=payload.workspace_id, project_id=left_version.project_id,
            name=payload.name.strip(), original_name=f"{payload.name.strip()}.csv",
            storage_key=storage_key, size_bytes=target.stat().st_size,
            profile=result_profile, semantics=semantics,
        )
        session.add(result_dataset)
        await session.flush()
        await ensure_dataset_version(session, result_dataset, project_id=left_version.project_id)
        relation.result_dataset_id = result_dataset.id
        await session.commit()
        await session.refresh(relation)
        await session.refresh(result_dataset)
        return await as_relationship(session, relation)
    except RelationshipValidationError as exc:
        await session.rollback()
        if target:
            target.unlink(missing_ok=True)
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        await session.rollback()
        if target:
            target.unlink(missing_ok=True)
        raise HTTPException(400, f"生成关联副本失败：{exc}") from exc


@app.get("/api/v1/dataset-relationships", response_model=list[DatasetRelationshipOut])
async def list_dataset_relationships(workspace_id: str, session: AsyncSession = Depends(get_session)):
    rows = (await session.scalars(
        select(DatasetRelationship).where(DatasetRelationship.workspace_id == workspace_id)
        .order_by(DatasetRelationship.created_at.desc())
    )).all()
    return [await as_relationship(session, item) for item in rows]


@app.get("/api/v1/samples")
async def list_samples():
    return [{
        "id": "retail-sales-2026", "name": "2026 零售经营示例数据", "filename": "retail_sales_2026.csv",
        "description": "48 条虚构销售记录，包含区域、渠道、品类、销售额、成本、订单、退货率和满意度。",
        "suggested_prompts": [
            "先介绍数据质量和字段含义，再告诉我最值得关注的三个问题。",
            "分析各区域销售额和利润差异，指出高退货率品类。",
            "生成一份管理层月度经营报告，包含结论、图表和行动建议。",
        ],
    }]


@app.post("/api/v1/samples/{sample_id}/import", response_model=DatasetOut, status_code=201)
async def import_sample(sample_id: str, workspace_id: str, session: AsyncSession = Depends(get_session)):
    if sample_id != "retail-sales-2026":
        raise HTTPException(404, "示例数据不存在")
    if not await session.get(Workspace, workspace_id):
        raise HTTPException(404, "工作区不存在")
    source = SAMPLE_DIR / "retail_sales_2026.csv"
    if not source.exists():
        raise HTTPException(500, "示例数据文件缺失")
    storage_key = new_storage_key(workspace_id, ".csv")
    target = storage_path(storage_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    frame = read_dataframe(storage_key)
    item = Dataset(
        workspace_id=workspace_id, name="2026 零售经营示例", original_name=source.name,
        storage_key=storage_key, size_bytes=target.stat().st_size, profile=profile_dataframe(frame),
    )
    session.add(item)
    await session.flush()
    await ensure_dataset_version(session, item)
    await session.commit()
    await session.refresh(item)
    return as_dataset(item)


@app.post("/api/v1/datasets/{dataset_id}/chart-preview", response_model=ChartPreviewResult)
async def chart_preview(dataset_id: str, payload: ChartPreviewRequest, session: AsyncSession = Depends(get_session)):
    dataset = await session.get(Dataset, dataset_id)
    if not dataset or dataset.workspace_id != payload.workspace_id:
        raise HTTPException(404, "数据集不存在或不属于当前工作区")
    frame = read_dataframe(dataset.storage_key)
    if payload.aggregate:
        forbidden = set((dataset.semantics or {}).get("non_additive_columns") or [])
        requested = {payload.y_column, *(payload.series_columns or [])}
        blocked = sorted(column for column in requested if column in forbidden)
        if blocked:
            raise HTTPException(400, "N:1 右表字段不可在展开明细上直接聚合，请选择原始右表：" + "、".join(blocked))
    columns = set(str(column) for column in frame.columns)
    if payload.x_column and payload.x_column not in columns:
        raise HTTPException(400, "维度字段不存在")
    requested_measures = list(dict.fromkeys([item for item in [payload.y_column, *payload.series_columns] if item]))
    if any(item not in columns for item in requested_measures):
        raise HTTPException(400, "指标字段不存在")
    if not payload.y_column:
        raise HTTPException(400, "请选择指标字段")
    measure = payload.y_column
    values_by_measure: dict[str, pd.Series] = {}
    for current in requested_measures:
        numeric = pd.to_numeric(frame[current], errors="coerce")
        if payload.aggregate == "count":
            values_by_measure[current] = frame[current].notna().astype(int)
        else:
            if numeric.notna().sum() == 0:
                raise HTTPException(400, f"指标字段“{current}”必须是数值，或将聚合改为计数")
            values_by_measure[current] = numeric
    if payload.x_column:
        operation = "mean" if payload.aggregate == "avg" else "sum" if payload.aggregate == "count" else payload.aggregate
        temporary = frame[[payload.x_column]].copy()
        for current, values in values_by_measure.items():
            temporary[current] = values
        grouped = temporary.groupby(payload.x_column, dropna=False)[requested_measures].agg(operation)
        if payload.aggregate in {"sum", "count"}:
            grouped = grouped.sort_values(measure, ascending=False)
        grouped = grouped.head(payload.limit).reset_index()
        data = []
        for _, row in grouped.iterrows():
            item = {payload.x_column: "(空值)" if pd.isna(row[payload.x_column]) else str(row[payload.x_column])}
            item.update({current: None if pd.isna(row[current]) else float(row[current]) for current in requested_measures})
            data.append(item)
    else:
        operation = "mean" if payload.aggregate == "avg" else "sum" if payload.aggregate == "count" else payload.aggregate
        result = values_by_measure[measure].agg(operation)
        data = [{"label": measure, "value": None if pd.isna(result) else float(result)}]
    return ChartPreviewResult(data=data)


@app.post("/api/v1/datasets/{dataset_id}/sql", response_model=SqlRunOut)
async def execute_dataset_sql(dataset_id: str, payload: SqlRunRequest, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    dataset = await session.get(Dataset, dataset_id)
    if not dataset or dataset.workspace_id != payload.workspace_id:
        raise HTTPException(404, "数据集不存在或不属于当前工作区")
    _, membership = await actor_for(session, payload.workspace_id, x_actor_id); require(membership, "analysis.execute")
    try:
        frame = read_dataframe(dataset.storage_key)
        validate_non_additive_sql(payload.sql, dataset.semantics)
        columns, rows, row_count, truncated, duration_ms = run_sql_query(frame, payload.sql, payload.max_rows)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, f"SQL 执行失败：{exc}") from exc
    evidence_id = f"sql-{uuid4().hex[:12]}"
    return SqlRunOut(
        columns=columns, rows=rows, row_count=row_count, truncated=truncated, duration_ms=duration_ms,
        evidence={
            "id": evidence_id, "statement": "SQL 查询结果", "method": "DuckDB 内存副本，只读 SELECT/WITH",
            "value": f"返回 {row_count} 行{'（已截断）' if truncated else ''}", "source_columns": columns,
            "data": rows[:50], "code": payload.sql,
        },
    )


@app.post("/api/v1/datasets/{dataset_id}/python", response_model=PythonRunOut)
async def execute_dataset_python(dataset_id: str, payload: PythonRunRequest, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    dataset = await session.get(Dataset, dataset_id)
    if not dataset or dataset.workspace_id != payload.workspace_id:
        raise HTTPException(404, "数据集不存在或不属于当前工作区")
    _, membership = await actor_for(session, payload.workspace_id, x_actor_id); require(membership, "analysis.execute")
    started = time.perf_counter()
    try:
        result = run_generated_python(payload.code, storage_path(dataset.storage_key), payload.timeout_seconds)
    except SandboxUnavailable as exc:
        raise HTTPException(503, "Python 隔离容器尚未配置；不会降级到宿主机执行") from exc
    except (ValueError, TimeoutError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return PythonRunOut(
        stdout=result.stdout, stderr=result.stderr, exit_code=result.exit_code,
        duration_ms=max(1, round((time.perf_counter() - started) * 1000)),
    )


@app.post("/api/v1/datasets/{dataset_id}/forecast", response_model=ForecastOut)
async def forecast_dataset(dataset_id: str, payload: ForecastRequest, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    dataset = await session.get(Dataset, dataset_id)
    if not dataset or dataset.workspace_id != payload.workspace_id:
        raise HTTPException(404, "数据集不存在或不属于当前工作区")
    _, membership = await actor_for(session, payload.workspace_id, x_actor_id); require(membership, "analysis.execute")
    try:
        result = forecast_time_series(read_dataframe(dataset.storage_key), **payload.model_dump(exclude={"workspace_id"}))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return ForecastOut(**result.__dict__)


@app.get("/api/v1/report-templates", response_model=list[ReportTemplateOut])
async def list_report_templates(workspace_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    _, membership = await actor_for(session, workspace_id, x_actor_id); require(membership, "template.use")
    result = await session.scalars(select(ReportTemplate).where(ReportTemplate.workspace_id == workspace_id).order_by(ReportTemplate.created_at.desc()))
    return [as_template(item) for item in result]


@app.post("/api/v1/report-templates/upload", response_model=ReportTemplateOut, status_code=201)
async def upload_report_template(
    workspace_id: str = Form(...), name: str = Form(default=""), file: UploadFile = File(...),
    x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session),
):
    actor, membership = await actor_for(session, workspace_id, x_actor_id); require(membership, "template.manage")
    original_name = Path(file.filename or "template.docx").name
    if Path(original_name).suffix.lower() != ".docx":
        raise HTTPException(400, "模板第一版仅支持 .docx，不接受 .docm、PDF 或宏文件")
    content = await file.read(MAX_TEMPLATE_BYTES + 1); await file.close()
    try:
        metadata = inspect_docx_template(content)
    except UnsafeTemplate as exc:
        raise HTTPException(400, str(exc)) from exc
    storage_key = f"workspaces/{workspace_id}/templates/{uuid4().hex}.docx"
    target = storage_path(storage_key); target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(content)
    item = ReportTemplate(
        workspace_id=workspace_id, name=(name.strip() or Path(original_name).stem)[:255], original_name=original_name,
        storage_key=storage_key, size_bytes=len(content), placeholders=metadata["placeholders"], metadata_json=metadata, created_by=actor.id,
    )
    session.add(item); await session.flush(); await audit(session, workspace_id, actor.id, "template.upload", "report_template", item.id, {"placeholders": metadata["placeholders"]}); await session.commit(); await session.refresh(item)
    return as_template(item)


@app.post("/api/v1/report-templates/{template_id}/render", response_model=ArtifactOut, status_code=201)
async def render_report_template(template_id: str, payload: TemplateRenderRequest, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    actor, membership = await actor_for(session, payload.workspace_id, x_actor_id); require(membership, "template.use")
    template = await session.get(ReportTemplate, template_id); report = await session.get(Report, payload.report_id)
    if not template or template.workspace_id != payload.workspace_id or not report or report.workspace_id != payload.workspace_id:
        raise HTTPException(404, "模板或报告不存在")
    rendered, metadata = render_docx_template(storage_path(template.storage_key), report, payload.mapping)
    storage_key = f"workspaces/{payload.workspace_id}/artifacts/{uuid4().hex}.docx"
    target = storage_path(storage_key); target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(rendered)
    item = GeneratedArtifact(workspace_id=payload.workspace_id, report_id=report.id, kind="docx-template", name=f"{report.title} - {template.name}.docx", storage_key=storage_key, metadata_json={"template_id": template.id, **metadata}, created_by=actor.id)
    session.add(item); await session.flush(); await audit(session, payload.workspace_id, actor.id, "template.render", "artifact", item.id, {"template_id": template.id, "report_id": report.id}); await session.commit(); await session.refresh(item)
    return as_artifact(item)


@app.get("/api/v1/artifacts/{artifact_id}/download")
async def download_artifact(artifact_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    item = await session.get(GeneratedArtifact, artifact_id)
    if not item: raise HTTPException(404, "导出文件不存在")
    _, membership = await actor_for(session, item.workspace_id, x_actor_id); require(membership, "template.use")
    path = storage_path(item.storage_key)
    if not path.is_file(): raise HTTPException(404, "导出文件已不存在")
    return FileResponse(path, filename=item.name, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.post("/api/v1/analysis/run", response_model=AnalysisResult)
async def run_analysis(payload: AnalysisRequest, session: AsyncSession = Depends(get_session)):
    dataset = await session.get(Dataset, payload.dataset_id)
    if not dataset or dataset.workspace_id != payload.workspace_id:
        raise HTTPException(404, "数据集不存在或不属于当前工作区")
    try:
        frame = read_dataframe(dataset.storage_key)
        profile = dataset.profile or profile_dataframe(frame)
        title = payload.report_title or f"{dataset.name} 分析报告"
        document = build_report(frame, profile, title, payload.prompt, dataset.semantics)
    except Exception as exc:
        raise HTTPException(400, f"分析失败：{exc}") from exc
    version = await ensure_dataset_version(session, dataset)
    report = Report(
        workspace_id=payload.workspace_id, project_id=version.project_id, dataset_id=dataset.id,
        dataset_version_id=version.id, title=document.title, document=document.model_dump(mode="json"),
    )
    session.add(report)
    await session.flush()
    await record_report_artifact(session, report)
    await session.commit()
    await session.refresh(report)
    return AnalysisResult(report_id=report.id, document=document, execution_mode="deterministic")


def _builtin_chart_patch(instruction: str, chart: ChartSpec) -> tuple[dict, list[str], list[str]]:
    """Safe local fallback when no model is configured or a model call fails."""
    text = instruction.casefold()
    patch: dict = {}
    rationale: list[str] = []
    warnings: list[str] = []
    type_words = {
        "横向条形图": "bar", "条形图": "bar", "柱状图": "bar", "折线图": "line", "面积图": "area",
        "散点图": "scatter", "气泡图": "bubble", "饼图": "pie", "环形图": "donut", "热力图": "heatmap",
        "树状图": "treemap", "直方图": "histogram", "箱线图": "boxplot", "瀑布图": "waterfall",
        "帕累托": "pareto", "控制图": "control_chart", "仪表盘": "gauge", "雷达图": "radar",
    }
    for word, chart_type in type_words.items():
        if word in text:
            patch["chart_type"] = chart_type
            rationale.append(f"按你的要求切换为{word}。")
            break
    style: dict = {}
    if any(word in text for word in ("横向", "水平")):
        style["orientation"] = "horizontal"
        rationale.append("横向条形图更适合较长的类别标签。")
    if any(word in text for word in ("堆叠", "累计")):
        style["stack"] = True
        rationale.append("已启用系列堆叠。")
    if any(word in text for word in ("商务", "管理层", "经营")):
        style["palette"] = "business"
    elif any(word in text for word in ("风险", "亏损", "警示")):
        style["palette"] = "risk"
    if any(word in text for word in ("标签", "标注数值", "显示数值")):
        style["show_labels"] = True
    if any(word in text for word in ("缩放", "放大", "时间窗口")):
        style["show_data_zoom"] = True
    if style:
        patch["style"] = {**chart.style.model_dump(mode="json"), **style}
    top_match = re.search(r"(?:top|前)\s*(\d{1,3})", text)
    if top_match:
        patch["limit"] = min(200, max(1, int(top_match.group(1))))
        rationale.append(f"仅保留排序靠前的 {patch['limit']} 项以提高可读性。")
    if not patch:
        warnings.append("未能从请求中识别确定的字段或图表调整；请描述目标图表、排序、Top N 或配色。")
    return patch, rationale or ["保留当前字段绑定，仅生成受控优化提案。"], warnings


async def _build_chart_proposal(
    report: Report, chart: ChartSpec, instruction: str, session: AsyncSession,
) -> ChartProposalOut:
    fallback, rationale, warnings = _builtin_chart_patch(instruction, chart)
    provider = await session.scalar(
        select(ProviderConfig).where(
            ProviderConfig.workspace_id == report.workspace_id,
            ProviderConfig.enabled.is_(True), ProviderConfig.encrypted_api_key != "",
        ).order_by(ProviderConfig.is_default.desc(), ProviderConfig.updated_at.desc()).limit(1)
    )
    builtin_alternatives = [
        ChartProposalAlternative(id="current", label="保守优化", patch=fallback, rationale=rationale),
        ChartProposalAlternative(
            id="accessible", label="无障碍配色", patch={"style": {**chart.style.model_dump(mode="json"), "palette": "accessible"}},
            rationale=["保留字段和图表结构，切换至色觉友好的配色以改善可访问性。"],
        ),
    ]
    if not provider:
        return ChartProposalOut(patch=fallback, rationale=rationale, warnings=warnings, alternatives=builtin_alternatives, provider="builtin")
    dataset = await session.get(Dataset, report.dataset_id) if report.dataset_id else None
    if not dataset:
        return ChartProposalOut(patch=fallback, rationale=rationale, warnings=[*warnings, "报告未绑定数据集，无法让 AI 修改字段。"], alternatives=builtin_alternatives, provider="builtin")
    try:
        await enforce_llm_budget(session, report.workspace_id)
        context = {
            "instruction": instruction,
            "current_chart": chart.model_dump(mode="json", exclude={"data"}),
            "available_fields": (dataset.profile or {}).get("columns", []),
            "allowed_chart_types": [
                "bar", "line", "area", "scatter", "bubble", "pie", "donut", "table", "highlight_table", "heatmap", "treemap",
                "histogram", "boxplot", "combo", "kpi", "waterfall", "pareto", "control_chart", "gauge", "radar", "density_plot",
            ],
        }
        prompt = chart_prompt(context)
        result = await complete(
            provider, [{"role": "user", "content": prompt}],
            "这是图表配置上下文，不含原始逐行数据。",
            request_options={"thinking": {"type": "disabled"}, "response_format": {"type": "json_object"}, "max_tokens": 1200},
        )
        raw = _extract_json_object(result.content)
        patch = raw.get("patch") if isinstance(raw.get("patch"), dict) else raw
        alternatives = []
        for index, item in enumerate(raw.get("alternatives", [])):
            if not isinstance(item, dict) or not isinstance(item.get("patch"), dict):
                continue
            alternatives.append(ChartProposalAlternative(
                id=re.sub(r"[^a-z0-9_-]", "-", str(item.get("id") or f"option-{index + 1}").casefold())[:40] or f"option-{index + 1}",
                label=str(item.get("label") or f"方案 {index + 1}")[:80], patch=item["patch"],
                rationale=item.get("rationale") if isinstance(item.get("rationale"), list) else [],
            ))
        validated = ChartProposalOut(
            patch=patch, rationale=raw.get("rationale") if isinstance(raw.get("rationale"), list) else rationale,
            warnings=raw.get("warnings") if isinstance(raw.get("warnings"), list) else warnings,
            alternatives=alternatives or builtin_alternatives,
            provider=provider.provider, usage=result.as_meta(),
        )
        session.add(usage_log(
            report.workspace_id, None, f"chart:{report.id}", provider, result,
            stage="chart", purpose="生成单图修改方案", report_id=report.id,
        ))
        await session.commit()
        return validated
    except Exception as exc:
        return ChartProposalOut(
            patch=fallback, rationale=rationale,
            warnings=[*warnings, f"模型提案不可用，已使用本地受控规则：{type(exc).__name__}"], alternatives=builtin_alternatives,
            provider=f"{provider.provider}-fallback",
        )


def _chart_patch_preview(report: Report, dataset: Dataset, chart_id: str, payload: ChartPatchPreviewRequest) -> ChartPatchPreviewOut:
    current = chart_by_id(report.document or {}, chart_id)
    current_version = chart_version_hint(current)
    if payload.base_version != current_version:
        raise HTTPException(409, "图表已被其他修改更新，请重新读取后再应用提案")
    updated = apply_chart_spec_patch(current, payload.patch)
    restricted = set((dataset.semantics or {}).get("non_additive_columns") or [])
    blocked = [field.column for field in [updated.y, *updated.series] if field and field.column in restricted]
    if blocked:
        raise HTTPException(400, "关联右表指标需回到原始粒度计算：" + "、".join(blocked))
    frame = read_dataframe(dataset.storage_key)
    data, computed = compute_chart_data(frame, updated, payload.patch.limit or 20)
    evidence_id = f"chart-compute-{chart_id}-{uuid4().hex[:10]}"
    computed_evidence = {
        "id": evidence_id,
        "statement": f"{updated.title} 的完整数据计算结果",
        "method": computed["method"],
        "value": f"返回 {computed['row_count']} 个绘图数据点",
        "source_columns": computed["source_columns"],
        "data": data[:50],
        "code": computed["code"],
        "dataset_id": dataset.id,
        "dataset_created_at": dataset.created_at.isoformat() if dataset.created_at else None,
    }
    final_chart = apply_computed_chart(updated, data, evidence_id)
    return ChartPatchPreviewOut(
        report_id=report.id, chart_id=chart_id, chart=final_chart, data=data,
        quality=quality_report(final_chart, data, (dataset.profile or {}).get("columns", [])),
        evidence=computed_evidence, base_version=current_version,
    )


@app.get("/api/v1/reports/{report_id}/charts/{chart_id}/context", response_model=ChartContextOut)
async def get_chart_context(report_id: str, chart_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    report, _, _ = await report_and_actor(report_id, x_actor_id, session, "report.view")
    if not report.dataset_id:
        raise HTTPException(409, "报告未绑定可重新计算的数据集")
    dataset = await session.get(Dataset, report.dataset_id)
    if not dataset:
        raise HTTPException(404, "报告关联的数据集不存在")
    chart = chart_by_id(report.document or {}, chart_id)
    data, _ = compute_chart_data(read_dataframe(dataset.storage_key), chart, 20)
    return ChartContextOut(
        report_id=report.id, report_title=report.title, dataset_id=dataset.id, chart=chart,
        fields=(dataset.profile or {}).get("columns", []), quality=quality_report(chart, data, (dataset.profile or {}).get("columns", [])),
        report_version_hint=chart_version_hint(chart),
    )


@app.post("/api/v1/reports/{report_id}/charts/{chart_id}/proposals", response_model=ChartProposalOut, response_model_exclude_none=True)
async def propose_chart_patch(report_id: str, chart_id: str, payload: ChartProposalRequest, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    report, _, membership = await report_and_actor(report_id, x_actor_id, session, "report.view")
    if report.workspace_id != payload.workspace_id:
        raise HTTPException(404, "报告不存在或不属于当前工作区")
    require(membership, "analysis.execute")
    chart = chart_by_id(report.document or {}, chart_id)
    return await _build_chart_proposal(report, chart, payload.instruction, session)


@app.post("/api/v1/reports/{report_id}/charts/{chart_id}/preview", response_model=ChartPatchPreviewOut)
async def preview_chart_patch(report_id: str, chart_id: str, payload: ChartPatchPreviewRequest, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    report, _, membership = await report_and_actor(report_id, x_actor_id, session, "report.view")
    if report.workspace_id != payload.workspace_id or not report.dataset_id:
        raise HTTPException(404, "报告或可重新计算的数据集不存在")
    require(membership, "analysis.execute")
    dataset = await session.get(Dataset, report.dataset_id)
    if not dataset:
        raise HTTPException(404, "报告关联的数据集不存在")
    try:
        return _chart_patch_preview(report, dataset, chart_id, payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/v1/reports/{report_id}/charts/{chart_id}/apply", response_model=ReportOut)
async def apply_chart_patch(report_id: str, chart_id: str, payload: ChartPatchApplyRequest, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    report, actor, membership = await report_and_actor(report_id, x_actor_id, session, "report.edit")
    if report.workspace_id != payload.workspace_id or not report.dataset_id:
        raise HTTPException(404, "报告或可重新计算的数据集不存在")
    require(membership, "analysis.execute")
    dataset = await session.get(Dataset, report.dataset_id)
    if not dataset:
        raise HTTPException(404, "报告关联的数据集不存在")
    try:
        preview = _chart_patch_preview(report, dataset, chart_id, payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    document = json.loads(json.dumps(report.document or {}, ensure_ascii=False, default=str))
    document["charts"] = [
        preview.chart.model_dump(mode="json") if item.get("id") == chart_id else item
        for item in document.get("charts") or []
    ]
    document.setdefault("evidence", []).append(preview.evidence)
    for block in document.get("blocks") or []:
        if block.get("kind") == "chart" and block.get("chart_id") == chart_id:
            block["evidence_ids"] = list(dict.fromkeys([*(block.get("evidence_ids") or []), preview.evidence["id"]]))
    validated = ReportDocument.model_validate(document)
    seal_chart(validated, chart_id)
    validated.quality = assess_report_quality(validated)
    session.add(ReportVersion(report_id=report.id, title=report.title, document=report.document))
    report.document = validated.model_dump(mode="json")
    await record_report_artifact(session, report)
    await audit(session, report.workspace_id, actor.id, "chart.apply", "chart", chart_id, {
        "report_id": report.id, "base_version": payload.base_version, "quality_score": preview.quality.score,
        "evidence_id": preview.evidence["id"],
    })
    await session.commit()
    await session.refresh(report)
    return as_report(report)


def _dashboard_layout_proposals(document: dict) -> list[ReportLayoutProposal]:
    """Deterministic twelve-column layout; the user reviews it before it is persisted."""
    proposals: list[ReportLayoutProposal] = []
    cursor_y = 0
    half_row_open = False
    for raw in document.get("charts") or []:
        chart = ChartSpec.model_validate(raw)
        if chart.chart_type == "kpi":
            position, reason = {"x": len([p for p in proposals if p.position["y"] == cursor_y]) * 3 % 12, "y": cursor_y, "w": 3, "h": 2}, "指标卡并列，优先展示关键数字。"
            if position["x"] >= 9:
                cursor_y += 2
        elif chart.chart_type in {"line", "area", "combo", "control_chart", "pareto", "waterfall"}:
            position, reason = {"x": 0, "y": cursor_y, "w": 12, "h": 5}, "趋势与组合图使用整行宽度，避免时间轴和双轴标签拥挤。"
            cursor_y += 5
            half_row_open = False
        elif chart.chart_type in {"table", "highlight_table", "heatmap"}:
            position, reason = {"x": 0, "y": cursor_y, "w": 12, "h": 6}, "明细/矩阵图使用整行宽度，保留可读行列空间。"
            cursor_y += 6
            half_row_open = False
        else:
            x = 6 if half_row_open else 0
            position, reason = {"x": x, "y": cursor_y, "w": 6, "h": 5}, "对比类图表按两列编排，便于横向比较。"
            half_row_open = not half_row_open
            if not half_row_open:
                cursor_y += 5
        proposals.append(ReportLayoutProposal(chart_id=chart.id, title=chart.title, position=position, reason=reason))
    return proposals


@app.post("/api/v1/reports/{report_id}/layout/proposals", response_model=ReportLayoutProposalOut)
async def propose_report_layout(report_id: str, payload: ReportLayoutRequest, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    report, _, _ = await report_and_actor(report_id, x_actor_id, session, "report.view")
    if report.workspace_id != payload.workspace_id:
        raise HTTPException(404, "报告不存在或不属于当前工作区")
    proposals = _dashboard_layout_proposals(report.document or {})
    return ReportLayoutProposalOut(report_id=report.id, proposals=proposals, summary=f"已根据 {len(proposals)} 个图表生成 12 列仪表板布局；不会改变图表字段或数据。")


@app.post("/api/v1/reports/{report_id}/layout/apply", response_model=ReportOut)
async def apply_report_layout(report_id: str, payload: ReportLayoutApplyRequest, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    report, actor, _ = await report_and_actor(report_id, x_actor_id, session, "report.edit")
    if report.workspace_id != payload.workspace_id:
        raise HTTPException(404, "报告不存在或不属于当前工作区")
    allowed = {item.get("id") for item in (report.document or {}).get("charts") or []}
    if any(item.chart_id not in allowed for item in payload.proposals):
        raise HTTPException(400, "布局包含不属于该报告的图表")
    document = json.loads(json.dumps(report.document or {}, ensure_ascii=False))
    positions = {item.chart_id: item.position for item in payload.proposals}
    for chart in document.get("charts") or []:
        if chart.get("id") in positions:
            chart["position"] = positions[chart["id"]]
    validated = ReportDocument.model_validate(document)
    validated.quality = assess_report_quality(validated)
    session.add(ReportVersion(report_id=report.id, title=report.title, document=report.document))
    report.document = validated.model_dump(mode="json")
    await record_report_artifact(session, report)
    await audit(session, report.workspace_id, actor.id, "report.layout.apply", "report", report.id, {"chart_count": len(positions)})
    await session.commit(); await session.refresh(report)
    return as_report(report)


@app.get("/api/v1/conversations", response_model=list[ConversationOut])
async def list_conversations(workspace_id: str, archived: bool = False, session: AsyncSession = Depends(get_session)):
    result = await session.scalars(
        select(Conversation).where(Conversation.workspace_id == workspace_id, Conversation.archived.is_(archived)).order_by(Conversation.updated_at.desc())
    )
    return [as_conversation(item) for item in result]


@app.post("/api/v1/conversations", response_model=ConversationOut, status_code=201)
async def create_conversation(payload: ConversationCreate, session: AsyncSession = Depends(get_session)):
    if not await session.get(Workspace, payload.workspace_id):
        raise HTTPException(404, "工作区不存在")
    dataset = None
    if payload.dataset_id:
        dataset = await session.get(Dataset, payload.dataset_id)
        if not dataset or dataset.workspace_id != payload.workspace_id:
            raise HTTPException(404, "数据集不存在或不属于当前工作区")
        await ensure_dataset_version(session, dataset)
    project = await backfill_workspace(session, payload.workspace_id)
    values = payload.model_dump()
    if "clarification_mode" not in payload.model_fields_set:
        settings = await session.scalar(select(AppSetting).where(AppSetting.workspace_id == payload.workspace_id))
        values["clarification_mode"] = (settings.settings or {}).get("default_clarification_mode", "auto") if settings else "auto"
    item = Conversation(**values, project_id=dataset.project_id if dataset else project.id)
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return as_conversation(item)


@app.patch("/api/v1/conversations/{conversation_id}", response_model=ConversationOut)
async def rename_conversation(conversation_id: str, payload: ConversationUpdate, session: AsyncSession = Depends(get_session)):
    item = await session.get(Conversation, conversation_id)
    if not item:
        raise HTTPException(404, "会话不存在")
    if payload.title is not None:
        item.title = payload.title
    if payload.clarification_mode is not None:
        item.clarification_mode = payload.clarification_mode
    if payload.analysis_capabilities is not None:
        item.analysis_capabilities = payload.analysis_capabilities.model_dump()
    item.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(item)
    return as_conversation(item)


@app.delete("/api/v1/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str, session: AsyncSession = Depends(get_session)):
    item = await session.get(Conversation, conversation_id)
    if not item:
        raise HTTPException(404, "会话不存在")
    active = await session.scalar(select(AnalysisRun.id).where(AnalysisRun.conversation_id == conversation_id, AnalysisRun.status.in_(["queued", "running"])))
    if active:
        raise HTTPException(409, "请先中断运行中的任务，再移除会话")
    item.archived = True
    await session.commit()


@app.post("/api/v1/conversations/{conversation_id}/restore", response_model=ConversationOut)
async def restore_conversation(conversation_id: str, session: AsyncSession = Depends(get_session)):
    item = await session.get(Conversation, conversation_id)
    if not item:
        raise HTTPException(404, "会话不存在")
    item.archived = False
    await session.commit()
    await session.refresh(item)
    return as_conversation(item)


@app.get("/api/v1/conversations/{conversation_id}/messages", response_model=list[ChatMessageOut])
async def list_messages(conversation_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    conversation = await session.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(404, "会话不存在")
    _, membership = await actor_for(session, conversation.workspace_id, x_actor_id)
    require(membership, "analysis.view")
    result = await session.scalars(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id).order_by(ChatMessage.created_at))
    permissions = ROLE_PERMISSIONS.get(membership.role, [])
    return [as_message_for_permissions(item, permissions) for item in result]


TOOL_PRESENTATION = {
    "dataset.profile": ("inspect", "读取数据画像", "确认行列规模、字段类型与可用指标。", "low"),
    "data.quality": ("quality", "检查数据质量", "统计缺失值、重复记录和字段质量风险。", "low"),
    "statistics.describe": ("statistics", "计算描述统计", "计算有效样本、均值、中位数、标准差和 95% 置信区间。", "low"),
    "research.inferential": ("research", "执行科研推断", "自动执行可用的 t 检验、ANOVA、卡方、回归、效应量和样本量提示。", "low"),
    "survey.profile": ("survey", "识别问卷量表", "检查候选量表题、作答分布和 Cronbach α。", "low"),
    "survey.cross_analysis": ("survey-cross", "执行问卷交叉分析", "计算分组差异和分类变量之间的卡方检验及 Cramér’s V。", "low"),
    "cleaning.recommend": ("cleaning", "生成清洗建议", "按风险顺序给出可在数据工作台执行的清洗步骤，不改写原文件。", "low"),
    "timeseries.forecast": ("forecast", "回测并生成预测", "对时间序列运行候选基线、留出集回测和 95% 预测区间。", "low"),
    "action.recommend": ("recommend", "生成可执行建议", "将发现整理为带优先级、风险、验证方法和证据引用的建议。", "low"),
    "report.build": ("report", "生成分析报告", "用确定性聚合生成可编辑图表、结论和证据链。", "medium"),
    "report.template.fill": ("template", "填充 Word 模板", "使用已批准的工作区模板生成 DOCX，不执行宏或外部链接。", "medium"),
    "superset.publish": ("superset", "发布专业看板", "把数据副本、图表和布局发布到 Superset；不会改写原数据。", "high"),
}


def _excluded_optional_tools(message: str) -> set[str]:
    excluded = set()
    for tool, terms in (("timeseries.forecast", "预测|forecast"), ("research.inferential", "推断统计|推断检验")):
        if re.search(rf"(?:不要|不做|无需|不需要|禁止|暂不|do not|without)[^。；;\n]{{0,16}}(?:{terms})", message, re.I):
            excluded.add(tool)
    return excluded


def _required_mode_steps(mode_id: str, message: str, dataset_id: str | None, options: AnalysisOptions | None = None) -> list[AnalysisPlanStep]:
    if not dataset_id:
        return []
    tools = list(ANALYSIS_MODES[mode_id].recommended_tools)
    options = options or AnalysisOptions()
    if mode_id == "explore" and any(word in message for word in ("报告", "图表", "可视化", "汇报")):
        tools.append("report.build")
    if options.forecast.enabled or any(word in message.casefold() for word in ("预测", "forecast", "未来趋势")):
        tools.append("timeseries.forecast")
    if options.include_recommendations or any(word in message for word in ("建议", "行动", "怎么办")):
        tools.append("action.recommend")
    if options.include_report and "report.build" not in tools:
        tools.append("report.build")
    if options.template_id:
        if "report.build" not in tools:
            tools.append("report.build")
        tools.append("report.template.fill")
    tools = list(dict.fromkeys(tools))
    tools = [tool for tool in tools if tool not in _excluded_optional_tools(message)]
    tools = [tool for tool in tools if tool not in {"report.build", "report.template.fill", "superset.publish"}] + [
        tool for tool in ("report.build", "report.template.fill", "superset.publish") if tool in tools
    ]
    steps: list[AnalysisPlanStep] = []
    for tool in tools:
        step_id, title, description, risk = TOOL_PRESENTATION[tool]
        arguments = {}
        if tool == "timeseries.forecast":
            arguments = options.forecast.model_dump(mode="json", exclude={"enabled"})
        elif tool == "report.template.fill":
            arguments = {"template_id": options.template_id}
        steps.append(AnalysisPlanStep(id=step_id, title=title, description=description, tool=tool, risk=risk, arguments=arguments))
    return steps


def _make_analysis_plan(message: str, dataset_id: str | None, analysis_mode: str = "auto", profile: dict | None = None, options: AnalysisOptions | None = None) -> AnalysisPlan:
    mode_id, reason = resolve_mode(analysis_mode, message, profile)
    steps = _required_mode_steps(mode_id, message, dataset_id, options)
    steps.append(AnalysisPlanStep(
        id="synthesize", title="整理分析结论", description="结合工具结果形成易读答复；模型不可改写统计事实。",
        tool="assistant.synthesize",
    ))
    return AnalysisPlan(
        id=f"plan-{uuid4().hex}", objective=message.strip(), dataset_id=dataset_id,
        analysis_mode=mode_id, mode_reason=reason, requires_approval=True, steps=steps,
    )


ALLOWED_AGENT_TOOLS = {
    "dataset.profile", "data.quality", "sql.query", "statistics.describe", "research.inferential", "survey.profile", "survey.cross_analysis",
    "cleaning.recommend", "data.clean.apply", "timeseries.forecast", "action.recommend", "report.build", "report.template.fill", "superset.publish", "assistant.synthesize",
    "mcp.call",
    *( ["python.run"] if SANDBOX_ENABLED and SANDBOX_IMAGE else [] ),
}


def _validated_step_arguments(tool: str, arguments: object, profile: dict | None) -> dict | None:
    values = dict(arguments) if isinstance(arguments, dict) else {}
    fields = {str(item.get("name")) for item in (profile or {}).get("columns", []) if item.get("name")}
    if not fields:
        return values
    for key, value in values.items():
        if key == "columns" or key.endswith("_columns"):
            if isinstance(value, list) and any(str(item) not in fields for item in value):
                return None
        elif key == "column" or key.endswith("_column"):
            if value is not None and str(value) not in fields:
                return None
    if tool == "sql.query" and values.get("sql"):
        sql = str(values["sql"])
        aliases = {match.group(1).replace('""', '"') for match in re.finditer(r'(?i)\bAS\s+"((?:""|[^"])*)"', sql)}
        quoted = {match.group(1).replace('""', '"') for match in re.finditer(r'"((?:""|[^"])*)"', sql)}
        if quoted - fields - aliases:
            return None
    if tool == "data.clean.apply":
        steps = values.get("steps")
        if not isinstance(steps, list) or not steps:
            return None
        if any(not isinstance(item, dict) or (item.get("column") and str(item["column"]) not in fields) for item in steps):
            return None
    return values


def _validate_model_plan(raw: dict, message: str, dataset_id: str | None, analysis_mode: str = "auto", profile: dict | None = None, options: AnalysisOptions | None = None) -> AnalysisPlan:
    mode_id, reason = resolve_mode(analysis_mode, message, profile)
    steps: list[AnalysisPlanStep] = []
    used_ids: set[str] = set()
    for index, item in enumerate(raw.get("steps") or []):
        tool = str(item.get("tool", ""))
        if tool not in ALLOWED_AGENT_TOOLS or tool in _excluded_optional_tools(message):
            continue
        arguments = _validated_step_arguments(tool, item.get("arguments"), profile)
        if arguments is None:
            continue
        step_id = re.sub(r"[^a-zA-Z0-9_-]", "-", str(item.get("id") or f"step-{index + 1}"))[:50]
        if step_id in used_ids:
            step_id = f"{step_id}-{index + 1}"
        used_ids.add(step_id)
        steps.append(AnalysisPlanStep(
            id=step_id, title=str(item.get("title") or tool)[:100],
            description=str(item.get("description") or "在受控环境中执行并保存证据。")[:300],
            tool=tool, risk="high" if tool in {"superset.publish", "mcp.call"} else "medium" if tool in {"report.build", "report.template.fill", "python.run", "data.clean.apply"} else "low",
            arguments=arguments,
        ))
        if len(steps) >= 8:
            break
    if dataset_id:
        required = _required_mode_steps(mode_id, message, dataset_id, options)
        for required_step in reversed(required):
            existing = next((step for step in steps if step.tool == required_step.tool), None)
            if existing is None:
                steps.insert(0, required_step)
            elif required_step.arguments:
                existing.arguments = {**existing.arguments, **required_step.arguments}
    if any(word in message for word in ("报告", "图表", "仪表盘", "可视化", "汇报")) and dataset_id and not any(step.tool == "report.build" for step in steps):
        steps.append(AnalysisPlanStep(id="report", title="生成证据化报告", description="使用本地确定性计算生成可编辑图表和报告。", tool="report.build", risk="medium"))
    steps = [step for step in steps if step.tool != "assistant.synthesize"] + [
        AnalysisPlanStep(id="synthesize", title="基于证据整理结论", description="只使用工具返回的数值形成答复。", tool="assistant.synthesize")
    ]
    return AnalysisPlan(
        id=f"plan-{uuid4().hex}", objective=message.strip(), dataset_id=dataset_id,
        analysis_mode=mode_id, mode_reason=reason, requires_approval=True, steps=steps,
    )


async def _chat_scope(payload: ChatRequest | ChatPlanRequest, session: AsyncSession) -> tuple[Conversation, Dataset | None, str | None]:
    conversation = await session.get(Conversation, payload.conversation_id)
    if not conversation or conversation.workspace_id != payload.workspace_id:
        raise HTTPException(404, "会话不存在或不属于当前工作区")
    if conversation.archived:
        raise HTTPException(409, "请先从回收站恢复会话")
    dataset_id = payload.dataset_id or conversation.dataset_id
    dataset = await session.get(Dataset, dataset_id) if dataset_id else None
    if dataset and dataset.workspace_id != payload.workspace_id:
        raise HTTPException(404, "数据集不存在或不属于当前工作区")
    if dataset:
        await ensure_dataset_version(session, dataset)
        conversation.project_id = dataset.project_id
    elif not conversation.project_id:
        conversation.project_id = (await backfill_workspace(session, payload.workspace_id)).id
    return conversation, dataset, dataset_id


async def _upsert_plan_message(
    session: AsyncSession, conversation: Conversation, payload: ChatPlanRequest, message_meta: dict,
) -> ChatMessage:
    if payload.resume_message_id:
        item = await session.get(ChatMessage, payload.resume_message_id)
        if not item or item.conversation_id != conversation.id or not ((item.message_meta or {}).get("intake") or (item.message_meta or {}).get('planning_job')):
            raise HTTPException(404, "待继续的澄清消息不存在")
        item.content = payload.message
        item.message_meta = message_meta
        return item
    item = ChatMessage(conversation_id=conversation.id, role="user", content=payload.message, message_meta=message_meta)
    session.add(item)
    return item


@app.post("/api/v1/chat/plan", response_model=ChatPlanResult)
async def plan_chat(payload: ChatPlanRequest, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    from .report_requirements import resolve_requirements, constrain_steps
    requirements = resolve_requirements(payload.message, payload.analysis_options.report_requirements.model_dump())
    payload.analysis_options.report_requirements = payload.analysis_options.report_requirements.model_validate(requirements)
    if requirements['exclude_forecast']:
        payload.analysis_options.forecast.enabled = False
    _, membership = await actor_for(session, payload.workspace_id, x_actor_id)
    require(membership, "analysis.execute")
    conversation, dataset, dataset_id = await _chat_scope(payload, session)
    if "capabilities" not in payload.analysis_options.model_fields_set:
        payload.analysis_options.capabilities = payload.analysis_options.capabilities.model_validate(conversation.analysis_capabilities or {})
    base_profile = dataset.profile if dataset else {}
    project = await session.get(Project, conversation.project_id) if conversation.project_id else None
    brief = AnalysisBrief.model_validate(project.analysis_brief or {}) if project else AnalysisBrief()
    if not (payload.report_id or payload.chart_id):
        intake = evaluate_intake(payload.message, base_profile, brief, conversation.clarification_mode or "auto")
        if intake.should_pause:
            if project:
                brief = apply_brief_update(
                    brief,
                    AnalysisBriefUpdate(workspace_id=payload.workspace_id, objective=payload.message),
                    intake,
                )
                project.analysis_brief = brief.model_dump(mode="json")
            plan = AnalysisPlan(
                id=f"intake-{uuid4().hex}", objective=payload.message.strip(), dataset_id=dataset_id,
                analysis_mode=payload.analysis_mode, mode_reason="需要先确认会影响报告质量的业务假设。",
                execution_mode=payload.execution_mode, requires_approval=False, blocked=True, steps=[],
            )
            user_message = await _upsert_plan_message(
                session, conversation, payload, {
                    "dataset_id": dataset_id, "analysis_mode": payload.analysis_mode,
                    "analysis_options": payload.analysis_options.model_dump(mode="json"),
                    "execution_mode": payload.execution_mode,
                    "analysis_plan": plan.model_dump(mode="json"),
                    "intake": intake.model_dump(mode="json"),
                },
            )
            conversation.dataset_id = dataset_id
            if conversation.title == "新分析":
                conversation.title = payload.message.strip().replace("\n", " ")[:32]
            conversation.updated_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(user_message)
            return ChatPlanResult(user_message=as_message(user_message), plan=plan, intake=intake)
    plan = _make_analysis_plan(payload.message, dataset_id, payload.analysis_mode, base_profile, payload.analysis_options)
    plan.execution_mode = payload.execution_mode
    chart_edit: dict | None = None
    if payload.report_id or payload.chart_id:
        if not payload.report_id or not payload.chart_id:
            raise HTTPException(400, "图表修改计划必须同时指定报告和图表")
        report, _, report_membership = await report_and_actor(payload.report_id, x_actor_id, session, "report.view")
        if report.workspace_id != payload.workspace_id:
            raise HTTPException(404, "报告不存在或不属于当前工作区")
        require(report_membership, "analysis.execute")
        chart = chart_by_id(report.document or {}, payload.chart_id)
        plan = AnalysisPlan(
            id=f"chart-plan-{uuid4().hex}", objective=payload.message.strip(), dataset_id=report.dataset_id,
            analysis_mode=payload.analysis_mode, mode_reason="已识别为当前图表修改请求；只生成受控图表配置，不直接改动报告。",
            execution_mode=payload.execution_mode, requires_approval=True,
            steps=[
                AnalysisPlanStep(id="chart-context", title="读取当前图表与字段约束", description=f"锁定“{chart.title}”的字段、样式与版本，用于防止覆盖他人修改。", tool="chart.context"),
                AnalysisPlanStep(id="chart-propose", title="生成多种图表设计方案", description="AI 只返回受控 ChartSpec 补丁；不会得到原始逐行数据，也不会执行代码或 SQL。", tool="chart.propose"),
                AnalysisPlanStep(id="chart-preview", title="用完整数据重新计算预览", description="比较方案质量、时间排序、可访问性、单位/来源与科研误差线提示；保存前仍需单独批准。", tool="chart.preview"),
            ],
        )
        chart_edit = {"report_id": report.id, "chart_id": chart.id, "instruction": payload.message}
    planning_meta: dict = {"provider": "builtin", "prompt_versions": PROMPT_VERSIONS}
    provider = await session.scalar(
        select(ProviderConfig).where(
            ProviderConfig.workspace_id == payload.workspace_id,
            ProviderConfig.enabled.is_(True), ProviderConfig.encrypted_api_key != "",
        ).order_by(ProviderConfig.is_default.desc(), ProviderConfig.updated_at.desc()).limit(1)
    )
    mcp_catalog = []
    mcp_rows = (await session.scalars(select(McpServer).where(McpServer.workspace_id == payload.workspace_id, McpServer.enabled.is_(True)))).all()
    for server in mcp_rows:
        cached = (server.tool_cache or {}).get("tools") or []
        allowed = set(server.tool_allowlist or [])
        tools = [{"name": tool.get("name"), "description": tool.get("description", "")} for tool in cached if tool.get("name") and (not allowed or tool.get("name") in allowed)]
        if tools:
            priority = {"generate_chart", "update_chart", "generate_dashboard", "add_chart_to_existing_dashboard", "get_chart_preview", "execute_sql", "list_datasets", "get_dataset_info"}
            tools.sort(key=lambda item: (item["name"] not in priority, item["name"]))
            mcp_catalog.append({"server_id": server.id, "server_name": server.name, "tools": tools[:30]})
    if provider and dataset and not chart_edit:
        completion = None
        try:
            await enforce_llm_budget(session, payload.workspace_id)
            profile = base_profile
            tool_lines = [
                "dataset.profile：读取完整字段画像", "data.quality：检查缺失、重复、常量列和日期",
                "sql.query：对表 dataset 执行只读 DuckDB SELECT/WITH，arguments.sql 必填",
                "statistics.describe：描述统计、标准差和 95% 置信区间",
                "research.inferential：t 检验、ANOVA、卡方、线性回归、效应量及样本量提示（自动选择合适字段）",
                "survey.profile：量表字段与 Cronbach alpha", "survey.cross_analysis：问卷分组/交叉表、卡方与 Cramér’s V",
                "cleaning.recommend：清洗建议，不改原文件",
                "data.clean.apply：按 arguments.steps 执行结构化清洗并生成新数据版本，永不覆盖原文件",
                "timeseries.forecast：确定性基线预测、回测和预测区间", "action.recommend：结构化行动建议",
                "report.build：生成本地计算的可编辑报告", "superset.publish：发布数据副本和专业看板",
                "assistant.synthesize：必须是最后一步",
            ]
            if mcp_catalog:
                tool_lines.append("mcp.call：调用已登记的 MCP 工具，arguments 必须包含 server_id、tool_name 和 arguments；所有 MCP 调用都属于外部操作，必须在计划中明确说明。")
            if "python.run" in ALLOWED_AGENT_TOOLS:
                tool_lines.insert(3, "python.run：隔离容器内运行 Python，arguments.code 必填")
            prompt = planner_prompt(
                message=payload.message, requested_mode=payload.analysis_mode,
                resolved_mode=plan.analysis_mode, reason=plan.mode_reason,
                analysis_options=payload.analysis_options.model_dump(mode="json"),
                tool_lines=tool_lines, mcp_catalog=mcp_catalog,
            )
            completion = await complete(
                provider, [{"role": "user", "content": prompt}],
                planning_context(
                    dataset_name=dataset.name, dataset_version_id=dataset.current_version_id,
                    profile=profile, semantics=dataset.semantics or {},
                    analysis_brief={
                        "answers": brief.answers,
                        "confirmed_keys": brief.confirmed_keys,
                        "defaulted_keys": brief.defaulted_keys,
                    },
                ),
                request_options={"thinking": {"type": "disabled"}, "response_format": {"type": "json_object"}, "max_tokens": 2000},
            )
            session.add(usage_log(
                payload.workspace_id, conversation.id, None, provider, completion,
                stage="planning", purpose="生成分析计划",
            ))
            plan = _validate_model_plan(_extract_json_object(completion.content), payload.message, dataset_id, payload.analysis_mode, profile, payload.analysis_options)
            plan.execution_mode = payload.execution_mode
            planning_meta = {"provider": provider.provider, "usage": completion.as_meta(), "prompt_versions": PROMPT_VERSIONS}
        except Exception as exc:
            planning_meta = {
                "provider": f"{provider.provider}-fallback", "error": f"{type(exc).__name__}: {str(exc)[:180]}",
                "usage": completion.as_meta() if completion else None,
                "raw_response": completion.content[:1000] if completion else "",
                "prompt_versions": PROMPT_VERSIONS,
            }
    plan.steps = configure_steps(plan.steps, payload.analysis_options.capabilities, bool(dataset_id))
    plan.report_requirements = payload.analysis_options.report_requirements
    plan.steps = constrain_steps(plan.steps, requirements, [c['name'] for c in base_profile.get('columns',[])])
    _apply_plan_policy(plan)
    resumed_message = await session.get(ChatMessage, payload.resume_message_id) if payload.resume_message_id else None
    intake_completed = bool(resumed_message and (resumed_message.message_meta or {}).get('intake'))
    user_message = await _upsert_plan_message(
        session, conversation, payload,
        {"dataset_id": dataset_id, "analysis_mode": plan.analysis_mode, "analysis_options": payload.analysis_options.model_dump(mode="json"), "execution_mode": payload.execution_mode, "analysis_plan": plan.model_dump(mode="json"), "planning": planning_meta, "chart_edit": chart_edit, "intake_completed": intake_completed},
    )
    conversation.dataset_id = dataset_id
    if conversation.title == "新分析":
        conversation.title = payload.message.strip().replace("\n", " ")[:32]
    conversation.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(user_message)
    return ChatPlanResult(user_message=as_message(user_message), plan=plan)


@app.post("/api/v1/chat/plans/{message_id}/cancel", response_model=ChatMessageOut)
async def cancel_chat_plan(message_id: str, workspace_id: str, conversation_id: str, session: AsyncSession = Depends(get_session)):
    conversation = await session.get(Conversation, conversation_id)
    message = await session.get(ChatMessage, message_id)
    if not conversation or conversation.workspace_id != workspace_id or not message or message.conversation_id != conversation_id:
        raise HTTPException(404, "分析计划不存在")
    meta = dict(message.message_meta or {})
    plan = dict(meta.get("analysis_plan") or {})
    if plan.get("status") not in {"pending", "cancelled"}:
        raise HTTPException(409, "只有待批准计划可以取消")
    plan["status"] = "cancelled"
    meta["analysis_plan"] = plan
    message.message_meta = meta
    await session.commit()
    await session.refresh(message)
    return as_message(message)


async def _execute_chat_plan(payload: ChatExecuteRequest, actor_id: str | None, session: AsyncSession, run_id: str | None = None) -> ChatResult:
    return await execute_plan(payload, actor_id, session, run_id, ports=ExecutionPorts(
        complete=complete, enforce_llm_budget=enforce_llm_budget, usage_log=usage_log,
        create_cleaned_copy=_create_cleaned_copy, publish_superset=_perform_superset_publish,
        append_event=_append_run_event,
    ))


@app.post("/api/v1/chat/execute", response_model=ChatResult)
async def execute_chat_plan(payload: ChatExecuteRequest, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    """Compatibility endpoint for a short, foreground run."""
    return await _execute_chat_plan(payload, x_actor_id, session)


async def _dispatch_run(payload, actor, session, run_id):
    from .planning_runtime import dispatch
    return await dispatch(payload, actor, session, run_id, plan=plan_chat, execute=_execute_chat_plan)


async def _run_analysis_task(run_id: str, actor_id: str | None) -> None:
    try:
        await run_background(run_id, actor_id, session_factory=SessionLocal,
                             execute=_dispatch_run, append_event=_append_run_event)
    finally:
        LOCAL_TASKS.pop(run_id, None)
        RUN_EVENT_LOCKS.pop(run_id, None)
        RUN_EVENT_SEQUENCES.pop(run_id, None)


from .delivery import serialize_local

@app.post('/api/v1/chat/plan-async', response_model=AnalysisRunOut, status_code=202)
@serialize_local
async def enqueue_planning(payload: ChatPlanRequest, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    _, membership=await actor_for(session,payload.workspace_id,x_actor_id)
    require(membership,'analysis.execute')
    conversation,dataset,_=await _chat_scope(payload,session)
    payload.dataset_id=dataset.id if dataset else None
    if 'capabilities' not in payload.analysis_options.model_fields_set:
        payload.analysis_options.capabilities = payload.analysis_options.capabilities.model_validate(conversation.analysis_capabilities or {})
    request_key=f'planning-request:{conversation.id}:{payload.idempotency_key}' if payload.idempotency_key else None
    if request_key:
        existing=await session.scalar(select(AnalysisRun).where(AnalysisRun.idempotency_key==request_key))
        if existing:
            if existing.analysis_spec.get('request')!=payload.model_dump(mode='json'):
                raise HTTPException(409,'幂等键已用于不同请求，请使用新键')
            return as_analysis_run(existing)
    message=ChatMessage(conversation_id=conversation.id,role='user',content=payload.message,message_meta={'planning_job':True})
    session.add(message); await session.flush()
    run=AnalysisRun(workspace_id=payload.workspace_id,project_id=conversation.project_id,conversation_id=conversation.id,
        plan_message_id=message.id,analysis_spec={'kind':'planning','request':payload.model_dump(mode='json')},
        dataset_version_ids=[dataset.current_version_id] if dataset else [],idempotency_key=request_key or f'planning:{message.id}',status='queued')
    session.add(run); await session.flush()
    await _append_run_event(session,run.id,'run.queued','queued','规划已排队；不会自动执行工具')
    await session.commit(); await session.refresh(run)
    _schedule_run(run.id,x_actor_id)
    return as_analysis_run(run)


@app.post("/api/v1/chat/execute-async", response_model=AnalysisRunOut, status_code=202)
@serialize_local
async def enqueue_chat_plan(payload: ChatExecuteRequest, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    conversation = await session.get(Conversation, payload.conversation_id)
    message = await session.get(ChatMessage, payload.plan_message_id)
    if not conversation or conversation.workspace_id != payload.workspace_id or not message or message.conversation_id != conversation.id:
        raise HTTPException(404, "分析计划不存在或不属于当前工作区")
    if conversation.archived:
        raise HTTPException(409, "请先从回收站恢复会话")
    _, membership = await actor_for(session, payload.workspace_id, x_actor_id)
    require(membership, "analysis.execute")
    plan = AnalysisPlan.model_validate((message.message_meta or {}).get("analysis_plan") or {})
    idempotency_key = f"plan:{message.id}:attempt:1"
    existing = await session.scalar(select(AnalysisRun).where(AnalysisRun.idempotency_key == idempotency_key))
    if existing:
        return as_analysis_run(existing)
    if plan.status != "pending":
        raise HTTPException(409, "该计划已执行或已取消")
    try:
        enforce_tools(plan.execution_mode, [step.tool for step in plan.steps], approved=payload.approved)
    except ToolPolicyError as exc:
        raise HTTPException(403 if "禁止" in str(exc) else 409, str(exc)) from exc
    dataset = await session.get(Dataset, conversation.dataset_id) if conversation.dataset_id else None
    version = await ensure_dataset_version(session, dataset) if dataset else None
    run = AnalysisRun(
        workspace_id=payload.workspace_id,
        project_id=(dataset.project_id if dataset else conversation.project_id),
        conversation_id=conversation.id, plan_message_id=message.id, status="queued",
        idempotency_key=idempotency_key, approval_granted=payload.approved,
        dataset_version_ids=[version.id] if version else [], analysis_spec=plan.model_dump(mode="json"),
    )
    session.add(run); await session.flush()
    await _append_run_event(session, run.id, "run.queued", "queued", "分析任务已进入本地队列")
    await session.commit(); await session.refresh(run)
    _schedule_run(run.id, x_actor_id)
    return as_analysis_run(run)


@app.get("/api/v1/analysis-runs", response_model=list[AnalysisRunOut])
async def list_analysis_runs(workspace_id: str, conversation_id: str | None = None, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    _, membership = await actor_for(session, workspace_id, x_actor_id); require(membership, "analysis.view")
    query = select(AnalysisRun).where(AnalysisRun.workspace_id == workspace_id).order_by(AnalysisRun.created_at.desc())
    if conversation_id:
        query = query.where(AnalysisRun.conversation_id == conversation_id)
    return [as_analysis_run(item) for item in (await session.scalars(query.limit(100))).all()]


@app.get("/api/v1/analysis-runs/{run_id}/events", response_model=list[RunEventOut])
async def list_analysis_run_events(run_id: str, workspace_id: str, after: int = 0, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    run = await session.get(AnalysisRun, run_id)
    if not run or run.workspace_id != workspace_id:
        raise HTTPException(404, "运行记录不存在")
    _, membership = await actor_for(session, workspace_id, x_actor_id); require(membership, "analysis.view")
    rows = (await session.scalars(
        select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.sequence > after).order_by(RunEvent.sequence)
    )).all()
    return [as_run_event(item) for item in rows]


@app.get("/api/v1/analysis-runs/{run_id}/events/stream")
async def stream_analysis_run_events(run_id: str, workspace_id: str, after: int = 0, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    run = await session.get(AnalysisRun, run_id)
    if not run or run.workspace_id != workspace_id:
        raise HTTPException(404, "运行记录不存在")
    _, membership = await actor_for(session, workspace_id, x_actor_id); require(membership, "analysis.view")

    async def event_stream():
        cursor = max(0, after)
        while True:
            async with SessionLocal() as event_session:
                rows = (await event_session.scalars(
                    select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.sequence > cursor).order_by(RunEvent.sequence)
                )).all()
                current_status = await event_session.scalar(select(AnalysisRun.status).where(AnalysisRun.id == run_id))
            for item in rows:
                cursor = item.sequence
                payload_json = json.dumps(as_run_event(item).model_dump(mode="json"), ensure_ascii=False)
                yield f"id: {item.sequence}\ndata: {payload_json}\n\n"
            if current_status in {"completed", "failed", "cancelled", "interrupted"} and not rows:
                break
            await asyncio.sleep(0.4)

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/v1/analysis-runs/{run_id}/cancel", response_model=AnalysisRunOut)
async def cancel_analysis_run(run_id: str, workspace_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    run = await session.get(AnalysisRun, run_id)
    if not run or run.workspace_id != workspace_id:
        raise HTTPException(404, "运行记录不存在")
    _, membership = await actor_for(session, workspace_id, x_actor_id); require(membership, "analysis.execute")
    if run.status not in {"queued", "running"}:
        raise HTTPException(409, "只有排队或运行中的任务可以取消")
    run.cancel_requested = True
    if run.status == "queued":
        transition_run(run, "cancelled"); run.finished_at = datetime.now(timezone.utc)
    await _append_run_event(session, run.id, "run.cancel.requested", run.status, "用户请求取消分析任务")
    await session.commit()
    task = LOCAL_TASKS.get(run.id)
    if task and not task.done():
        task.cancel()
    await session.refresh(run)
    return as_analysis_run(run)


@app.post("/api/v1/analysis-runs/{run_id}/retry", response_model=AnalysisRunOut, status_code=202)
@serialize_local
async def retry_analysis_run(run_id: str, workspace_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    previous = await session.get(AnalysisRun, run_id)
    if not previous or previous.workspace_id != workspace_id:
        raise HTTPException(404, "运行记录不存在")
    _, membership = await actor_for(session, workspace_id, x_actor_id); require(membership, "analysis.execute")
    if previous.status not in {"failed", "cancelled", "interrupted"}:
        raise HTTPException(409, "只有失败、已取消或被中断的运行可以重试")
    if (previous.analysis_spec or {}).get('kind') == 'planning':
        from .planning_retry import prepare_retry
        run, created = await prepare_retry(session, previous)
        if created:
            await _append_run_event(session, run.id, 'run.queued', 'queued', '规划重试已排队')
            await session.commit()
            await session.refresh(run)
            _schedule_run(run.id, x_actor_id)
        return as_analysis_run(run)
    message = await session.get(ChatMessage, previous.plan_message_id)
    meta = dict(message.message_meta or {}) if message else {}
    plan_data = dict(meta.get("analysis_plan") or {})
    if not message or not plan_data:
        raise HTTPException(409, "原分析计划已不可用")
    plan_data["status"] = "pending"; meta["analysis_plan"] = plan_data; message.message_meta = meta
    idempotency_key = f"plan:{previous.plan_message_id}:attempt:{previous.attempt + 1}"
    existing = await session.scalar(select(AnalysisRun).where(AnalysisRun.idempotency_key == idempotency_key))
    if existing:
        return as_analysis_run(existing)
    run = AnalysisRun(
        workspace_id=workspace_id, project_id=previous.project_id,
        conversation_id=previous.conversation_id, plan_message_id=previous.plan_message_id,
        status="queued", attempt=previous.attempt + 1,
        idempotency_key=idempotency_key, approval_granted=previous.approval_granted,
        dataset_version_ids=previous.dataset_version_ids or [], analysis_spec=previous.analysis_spec or plan_data,
    )
    session.add(run); await session.flush()
    await _append_run_event(session, run.id, "run.queued", "queued", f"第 {run.attempt} 次运行已进入本地队列")
    await session.commit(); await session.refresh(run)
    _schedule_run(run.id, x_actor_id)
    return as_analysis_run(run)


@app.post("/api/v1/chat", response_model=ChatResult)
async def send_chat(payload: ChatRequest, session: AsyncSession = Depends(get_session)):
    conversation = await session.get(Conversation, payload.conversation_id)
    if not conversation or conversation.workspace_id != payload.workspace_id:
        raise HTTPException(404, "会话不存在或不属于当前工作区")
    dataset_id = payload.dataset_id or conversation.dataset_id
    dataset = await session.get(Dataset, dataset_id) if dataset_id else None
    if dataset and dataset.workspace_id != payload.workspace_id:
        raise HTTPException(404, "数据集不存在或不属于当前工作区")
    dataset_version = await ensure_dataset_version(session, dataset) if dataset else None
    if dataset:
        conversation.project_id = dataset.project_id

    user_message = ChatMessage(conversation_id=conversation.id, role="user", content=payload.message, message_meta={"dataset_id": dataset_id})
    session.add(user_message)
    conversation.dataset_id = dataset_id
    if conversation.title == "新分析":
        conversation.title = payload.message.strip().replace("\n", " ")[:32]
    conversation.updated_at = datetime.now(timezone.utc)
    await session.flush()

    profile = dataset.profile if dataset else {}
    context = "尚未选择数据集。"
    if dataset:
        column_names = [item.get("name") for item in profile.get("columns", [])]
        context = f"数据集：{dataset.name}；{profile.get('row_count', 0)} 行，{profile.get('column_count', 0)} 列；字段：{', '.join(column_names)}。"

    report_id = None
    report_words = ("报告", "图表", "仪表盘", "可视化", "汇报")
    if dataset and any(word in payload.message for word in report_words):
        frame = read_dataframe(dataset.storage_key)
        document = build_report(frame, profile, f"{dataset.name} 分析报告", payload.message, dataset.semantics)
        project = await session.get(Project, dataset_version.project_id)
        document = apply_brief_to_report(document, AnalysisBrief.model_validate(project.analysis_brief or {}))
        report = Report(
            workspace_id=payload.workspace_id, project_id=dataset_version.project_id,
            dataset_id=dataset.id, dataset_version_id=dataset_version.id,
            title=document.title, document=document.model_dump(mode="json"),
        )
        session.add(report)
        await session.flush()
        await record_report_artifact(session, report)
        report_id = report.id
        context += f" 系统已调用确定性分析工具生成报告《{document.title}》，含 {len(document.charts)} 个图表和 {len(document.evidence)} 条证据。"

    provider = await session.scalar(
        select(ProviderConfig).where(
            ProviderConfig.workspace_id == payload.workspace_id,
            ProviderConfig.enabled.is_(True),
            ProviderConfig.encrypted_api_key != "",
        ).order_by(ProviderConfig.is_default.desc(), ProviderConfig.updated_at.desc()).limit(1)
    )
    provider_name = "builtin"
    usage_meta = None
    if provider:
        spent_before = await enforce_llm_budget(session, payload.workspace_id)
        history_result = await session.scalars(
            select(ChatMessage).where(ChatMessage.conversation_id == conversation.id).order_by(ChatMessage.created_at.desc()).limit(20)
        )
        history = list(reversed(list(history_result)))
        try:
            completion = await complete(provider, [{"role": item.role, "content": item.content} for item in history], context)
            assistant_text = completion.content
            provider_name = provider.provider
            usage_meta = {**completion.as_meta(), "daily_spend_before_cny": round(spent_before, 8), "daily_budget_cny": DAILY_LLM_BUDGET_CNY}
            session.add(usage_log(
                payload.workspace_id, conversation.id, None, provider, completion,
                stage="synthesis", purpose="生成对话分析回复",
            ))
        except Exception as exc:
            assistant_text = _builtin_reply(dataset, profile, report_id, provider_error=f"{type(exc).__name__}: {str(exc)[:120]}")
            provider_name = f"{provider.provider}-fallback"
    else:
        assistant_text = _builtin_reply(dataset, profile, report_id)

    assistant_meta = {"dataset_id": dataset_id, "report_id": report_id, "provider": provider_name, "usage": usage_meta}
    assistant_message = ChatMessage(conversation_id=conversation.id, role="assistant", content=assistant_text, message_meta=assistant_meta)
    session.add(assistant_message)
    await session.commit()
    await session.refresh(user_message)
    await session.refresh(assistant_message)
    return ChatResult(user_message=as_message(user_message), assistant_message=as_message(assistant_message), report_id=report_id, provider=provider_name)


def _builtin_reply(dataset: Dataset | None, profile: dict, report_id: str | None, provider_error: str | None = None) -> str:
    if not dataset:
        answer = "请选择或上传一份数据。我会先检查字段、缺失值和数据规模，再与你逐步确认分析目标。你也可以点击“载入示例数据”直接体验。"
    else:
        columns = profile.get("columns", [])
        null_columns = [item["name"] for item in columns if item.get("null_count", 0) > 0]
        answer = f"我已连接“{dataset.name}”，共 {profile.get('row_count', 0):,} 行、{profile.get('column_count', 0)} 列。"
        answer += f" 检测到缺失值字段：{', '.join(null_columns)}。" if null_columns else " 当前字段剖析未发现缺失值。"
        if report_id:
            answer += "\n\n已调用受控统计工具生成一份可编辑报告。点击下方报告卡片进入专业编辑器；数字和图表来自确定性计算，发布前请确认业务解释。"
        else:
            answer += "\n\n你可以继续问：哪些区域贡献最高、利润与退货率是否异常，或者让我生成管理层报告。"
    if provider_error:
        answer += f"\n\n模型服务暂时不可用，已切换为本地助手。诊断信息：{provider_error}"
    return answer


@app.get("/api/v1/settings/providers", response_model=list[ProviderConfigOut])
async def list_provider_settings(workspace_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.scalars(select(ProviderConfig).where(ProviderConfig.workspace_id == workspace_id))
    by_name = {item.provider: item for item in result}
    return [as_provider(by_name.get(name), name) for name in ("openai", "deepseek")]


@app.put("/api/v1/settings/providers/{provider}", response_model=ProviderConfigOut)
async def save_provider_settings(provider: str, workspace_id: str, payload: ProviderConfigUpdate, session: AsyncSession = Depends(get_session)):
    if provider not in PROVIDER_DEFAULTS:
        raise HTTPException(404, "不支持的模型提供商")
    if not await session.get(Workspace, workspace_id):
        raise HTTPException(404, "工作区不存在")
    base_url = validate_provider_url(payload.base_url)
    item = await session.scalar(select(ProviderConfig).where(ProviderConfig.workspace_id == workspace_id, ProviderConfig.provider == provider))
    if not item:
        item = ProviderConfig(workspace_id=workspace_id, provider=provider, base_url=base_url, model=payload.model)
        session.add(item)
    if payload.is_default:
        await session.execute(update(ProviderConfig).where(ProviderConfig.workspace_id == workspace_id).values(is_default=False))
    item.enabled = payload.enabled
    item.is_default = payload.is_default
    item.base_url = base_url
    item.model = payload.model
    item.options = payload.options
    if payload.clear_api_key:
        item.encrypted_api_key = ""
    elif payload.api_key:
        item.encrypted_api_key = encrypt_secret(payload.api_key.strip())
    await session.commit()
    await session.refresh(item)
    return as_provider(item, provider)


@app.post("/api/v1/settings/providers/{provider}/test", response_model=ProviderTestResult)
async def test_provider_settings(provider: str, workspace_id: str, session: AsyncSession = Depends(get_session)):
    item = await session.scalar(select(ProviderConfig).where(ProviderConfig.workspace_id == workspace_id, ProviderConfig.provider == provider))
    if not item or not item.encrypted_api_key:
        return ProviderTestResult(ok=False, message="请先保存 API Key")
    ok, message, latency = await test_provider(item)
    return ProviderTestResult(ok=ok, message=message, latency_ms=latency)


@app.get("/api/v1/mcp/servers", response_model=list[McpServerOut])
async def list_mcp_servers(workspace_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    _, membership = await actor_for(session, workspace_id, x_actor_id); require(membership, "analysis.view")
    result = await session.scalars(select(McpServer).where(McpServer.workspace_id == workspace_id).order_by(McpServer.updated_at.desc()))
    return [as_mcp_server(item) for item in result]


@app.post("/api/v1/mcp/servers", response_model=McpServerOut, status_code=201)
async def create_mcp_server(payload: McpServerCreate, workspace_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    actor, membership = await actor_for(session, workspace_id, x_actor_id); require(membership, "report.publish")
    item = McpServer(
        workspace_id=workspace_id, name=payload.name.strip(), url=validate_provider_url(payload.url), transport=payload.transport,
        enabled=payload.enabled, tool_allowlist=list(dict.fromkeys(payload.tool_allowlist)),
        encrypted_bearer_token=encrypt_secret(payload.bearer_token.strip()) if payload.bearer_token else "",
    )
    session.add(item); await session.flush()
    await audit(session, workspace_id, actor.id, "mcp.server.create", "mcp_server", item.id, {"name": item.name, "url": item.url})
    await session.commit(); await session.refresh(item)
    return as_mcp_server(item)


@app.patch("/api/v1/mcp/servers/{server_id}", response_model=McpServerOut)
async def update_mcp_server(server_id: str, payload: McpServerUpdate, workspace_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    actor, membership = await actor_for(session, workspace_id, x_actor_id); require(membership, "report.publish")
    item = await session.get(McpServer, server_id)
    if not item or item.workspace_id != workspace_id: raise HTTPException(404, "MCP 服务不存在")
    if payload.name is not None: item.name = payload.name.strip()
    if payload.url is not None: item.url = validate_provider_url(payload.url)
    if payload.transport is not None: item.transport = payload.transport
    if payload.enabled is not None: item.enabled = payload.enabled
    if payload.tool_allowlist is not None: item.tool_allowlist = list(dict.fromkeys(payload.tool_allowlist))
    if payload.clear_bearer_token: item.encrypted_bearer_token = ""
    elif payload.bearer_token: item.encrypted_bearer_token = encrypt_secret(payload.bearer_token.strip())
    await audit(session, workspace_id, actor.id, "mcp.server.update", "mcp_server", item.id, {"enabled": item.enabled, "url": item.url})
    await session.commit(); await session.refresh(item)
    return as_mcp_server(item)


@app.post("/api/v1/mcp/servers/{server_id}/discover", response_model=McpServerTestOut)
async def discover_mcp_server(server_id: str, workspace_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    actor, membership = await actor_for(session, workspace_id, x_actor_id); require(membership, "report.publish")
    item = await session.get(McpServer, server_id)
    if not item or item.workspace_id != workspace_id: raise HTTPException(404, "MCP 服务不存在")
    try:
        tools, latency = await list_mcp_tools(item)
        safe_tools = [{"name": str(tool.get("name", ""))[:160], "description": str(tool.get("description", ""))[:600], "inputSchema": tool.get("inputSchema") or {}} for tool in tools if tool.get("name")]
        item.tool_cache = {"tools": safe_tools, "discovered_at": datetime.now(timezone.utc).isoformat()}
        item.last_checked_at = datetime.now(timezone.utc)
        await audit(session, workspace_id, actor.id, "mcp.server.discover", "mcp_server", item.id, {"tool_count": len(safe_tools)})
        await session.commit()
        return McpServerTestOut(ok=True, message=f"连接成功，发现 {len(safe_tools)} 个 MCP 工具", latency_ms=latency, tools=safe_tools)
    except Exception as exc:
        return McpServerTestOut(ok=False, message=f"连接失败：{type(exc).__name__}: {str(exc)[:240]}", tools=[])


@app.get("/api/v1/usage/llm")
async def get_llm_usage(workspace_id: str, limit: int = 20, session: AsyncSession = Depends(get_session)):
    if not await session.get(Workspace, workspace_id):
        raise HTTPException(404, "工作区不存在")
    recent = await session.scalars(
        select(LlmUsageLog).where(LlmUsageLog.workspace_id == workspace_id)
        .order_by(LlmUsageLog.created_at.desc()).limit(max(1, min(limit, 100)))
    )
    rows = list(recent)
    spent_today = await daily_llm_spend(session, workspace_id)
    return {
        "workspace_id": workspace_id, "spent_today_cny": round(spent_today, 8),
        "daily_budget_cny": DAILY_LLM_BUDGET_CNY,
        "remaining_today_cny": round(max(0.0, DAILY_LLM_BUDGET_CNY - spent_today), 8),
        "recent": [{
            "id": item.id, "conversation_id": item.conversation_id, "plan_id": item.plan_id,
            "provider": item.provider, "model": item.model, "request_id": item.request_id,
            "prompt_tokens": item.prompt_tokens, "cache_hit_tokens": item.cache_hit_tokens,
            "cache_miss_tokens": item.cache_miss_tokens, "completion_tokens": item.completion_tokens,
            "total_tokens": item.total_tokens, "estimated_cost_cny": item.estimated_cost_cny,
            "latency_ms": item.latency_ms, "status": item.status, "created_at": item.created_at,
        } for item in rows],
    }


@app.get("/api/v1/usage/tokens", response_model=TokenUsageSummary)
async def get_token_usage(
    workspace_id: str,
    usage_range: Literal["today", "7d", "all"] = Query(default="7d", alias="range"),
    group_by: Literal["stage", "model", "run", "report", "dashboard"] = "stage",
    session: AsyncSession = Depends(get_session),
):
    if not await session.get(Workspace, workspace_id):
        raise HTTPException(404, "工作区不存在")
    return await summarize_token_usage(session, workspace_id, usage_range, group_by)


@app.get("/api/v1/usage/tokens/runs/{run_id}", response_model=TokenUsageSummary)
async def get_run_token_usage(run_id: str, workspace_id: str, session: AsyncSession = Depends(get_session)):
    if not await session.get(Workspace, workspace_id):
        raise HTTPException(404, "工作区不存在")
    return await summarize_token_usage(session, workspace_id, "all", "stage", run_id=run_id)


@app.get("/api/v1/usage/tokens/reports/{report_id}", response_model=TokenUsageSummary)
async def get_report_token_usage(report_id: str, workspace_id: str, session: AsyncSession = Depends(get_session)):
    if not await session.get(Workspace, workspace_id):
        raise HTTPException(404, "工作区不存在")
    return await summarize_token_usage(session, workspace_id, "all", "stage", report_id=report_id)


@app.get("/api/v1/settings/app", response_model=AppSettingsOut)
async def get_app_settings(workspace_id: str, session: AsyncSession = Depends(get_session)):
    item = await session.scalar(select(AppSetting).where(AppSetting.workspace_id == workspace_id))
    return AppSettingsOut(workspace_id=workspace_id, **(item.settings if item else DEFAULT_APP_SETTINGS))


@app.put("/api/v1/settings/app", response_model=AppSettingsOut)
async def save_app_settings(workspace_id: str, payload: AppSettingsUpdate, session: AsyncSession = Depends(get_session)):
    if not await session.get(Workspace, workspace_id):
        raise HTTPException(404, "工作区不存在")
    # The local edition never executes model-generated code on the host. This is
    # a server-side invariant, not a preference that a crafted request may lower.
    safe_settings = payload.model_dump()
    safe_settings["safe_mode"] = True
    item = await session.scalar(select(AppSetting).where(AppSetting.workspace_id == workspace_id))
    if not item:
        item = AppSetting(workspace_id=workspace_id, settings=safe_settings)
        session.add(item)
    else:
        item.settings = safe_settings
    await session.commit()
    return AppSettingsOut(workspace_id=workspace_id, **safe_settings)


@app.get("/api/v1/analysis-capabilities/reserved")
async def reserved_analysis_capabilities():
    return reserved_capabilities()


@app.get('/api/v1/analysis-capabilities/extensions')
async def builtin_extension_manifests():
    from .extensions import manifests
    return manifests()


@app.get("/api/v1/analysis-modes")
async def analysis_modes():
    return {"default": "auto", "modes": mode_catalog()}


@app.get("/api/v1/tools")
async def tool_manifest():
    return {
        "tiers": [
            {"id": "builtin", "name": "快速分析", "available": True, "network": False, "description": "DuckDB/Pandas 等确定性内置工具，可直接执行。"},
            {"id": "sandbox", "name": "受限代码执行", "available": SANDBOX_ENABLED and bool(SANDBOX_IMAGE), "network": False, "description": "仅允许在隔离容器中运行生成代码；默认关闭。"},
            {"id": "external", "name": "外部连接器", "available": bool(SUPERSET_URL and CURATED_DATABASE_URL), "network": True, "description": "Superset 正式发布始终需要用户批准分析计划。"},
        ],
        "policy": {
            "generated_code_on_host": False, "readonly_dataset_mount": True, "network_default": "deny",
            "original_file_mutation": "forbid", "formal_publish_requires_human": True,
            "modes": {
                mode: [decision.as_dict() for decision in evaluate_tools(mode, [
                    "dataset.profile", "data.quality", "statistics.describe", "sql.query",
                    "python.run", "data.clean.apply", "mcp.call", "superset.publish",
                ])]
                for mode in ("safe", "partial", "full")
            },
        },
    }


@app.get("/api/v1/integrations")
async def integrations():
    return await integration_status()


async def _upsert_external_resource(
    session: AsyncSession, *, workspace_id: str, resource_type: str, external_id: str,
    metadata: dict, actor_id: str | None,
) -> ExternalResource:
    item = await session.scalar(select(ExternalResource).where(
        ExternalResource.workspace_id == workspace_id, ExternalResource.provider == "superset",
        ExternalResource.resource_type == resource_type, ExternalResource.external_id == external_id,
    ))
    if item:
        item.metadata_json = metadata
        item.created_by = actor_id
    else:
        item = ExternalResource(
            workspace_id=workspace_id, provider="superset", resource_type=resource_type,
            external_id=external_id, metadata_json=metadata, created_by=actor_id,
        )
        session.add(item)
    return item


async def _perform_superset_publish(
    *, session: AsyncSession, actor_id: str, workspace_id: str, dataset: Dataset, report: Report,
    title: str, allowed_domains: list[str], frame: pd.DataFrame | None = None,
) -> dict:
    dashboard_rows = (await session.scalars(select(ExternalResource).where(
        ExternalResource.workspace_id == workspace_id, ExternalResource.provider == "superset",
        ExternalResource.resource_type == "dashboard",
    ).order_by(ExternalResource.created_at.desc()))).all()
    dashboard_mapping = next((item for item in dashboard_rows if (item.metadata_json or {}).get("dataset_id") == dataset.id), None)
    if not dashboard_mapping:
        dashboard_mapping = next((item for item in dashboard_rows if not (item.metadata_json or {}).get("dataset_id")), None)
    dashboard_id = (dashboard_mapping.metadata_json or {}).get("dashboard_id") if dashboard_mapping else None
    embedded_id = dashboard_mapping.external_id if dashboard_mapping else None
    document = report.document or {}
    publish_result = await publish_superset_dashboard(
        frame=frame if frame is not None else read_dataframe(dataset.storage_key), local_dataset_id=dataset.id,
        dataset_name=dataset.name, charts=document.get("charts") or [], title=title,
        allowed_domains=allowed_domains, dashboard_id=int(dashboard_id) if dashboard_id else None, embedded_id=embedded_id,
    )
    await _upsert_external_resource(
        session, workspace_id=workspace_id, resource_type="database", external_id=str(publish_result["database_id"]),
        metadata={"name": "Insight Studio Curated", "readonly_copy": True}, actor_id=actor_id,
    )
    await _upsert_external_resource(
        session, workspace_id=workspace_id, resource_type="dataset", external_id=str(publish_result["superset_dataset_id"]),
        metadata={"local_dataset_id": dataset.id, "name": dataset.name, "table_name": publish_result["table_name"]}, actor_id=actor_id,
    )
    for chart in publish_result["charts"]:
        await _upsert_external_resource(
            session, workspace_id=workspace_id, resource_type="chart", external_id=str(chart["id"]),
            metadata={"local_dataset_id": dataset.id, **chart}, actor_id=actor_id,
        )
    dashboard_metadata = {
        "dashboard_id": publish_result["dashboard_id"], "title": publish_result["title"],
        "dataset_id": dataset.id, "report_id": report.id, "dashboard_url": publish_result["dashboard_url"],
        "chart_count": len(publish_result["charts"]), "published": True,
    }
    if dashboard_mapping:
        dashboard_mapping.external_id = str(publish_result["embedded_id"])
        dashboard_mapping.metadata_json = dashboard_metadata
        dashboard_mapping.created_by = actor_id
    else:
        session.add(ExternalResource(
            workspace_id=workspace_id, provider="superset", resource_type="dashboard",
            external_id=str(publish_result["embedded_id"]), metadata_json=dashboard_metadata, created_by=actor_id,
        ))
    await audit(
        session, workspace_id, actor_id, "superset.publish", "dashboard", str(publish_result["dashboard_id"]),
        {"dataset_id": dataset.id, "report_id": report.id, "chart_count": len(publish_result["charts"]), "readonly_copy": True},
    )
    await session.flush()
    return {"status": "published", "dataset_id": dataset.id, **publish_result}


@app.post("/api/v1/integrations/superset/publish-preview")
async def preview_superset_publish(payload: SupersetPublishPreviewRequest, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    _, membership = await actor_for(session, payload.workspace_id, x_actor_id)
    require(membership, "report.view")
    dataset = await session.get(Dataset, payload.dataset_id)
    if not dataset or dataset.workspace_id != payload.workspace_id:
        raise HTTPException(404, "数据集不存在或不属于当前工作区")
    report = await session.get(Report, payload.report_id) if payload.report_id else None
    if report and (report.workspace_id != payload.workspace_id or report.dataset_id != dataset.id):
        raise HTTPException(404, "报告不存在或不属于当前数据集")
    if report:
        document = report.document or {}
    else:
        frame = read_dataframe(dataset.storage_key)
        document = build_report(frame, dataset.profile or profile_dataframe(frame), payload.title or f"{dataset.name} 分析报告", "生成 Superset 专业看板", dataset.semantics).model_dump(mode="json")
    return {
        "dataset_id": dataset.id, "dataset_name": dataset.name, "row_count": dataset.profile.get("row_count", 0),
        "title": payload.title or f"{dataset.name} 专业分析看板", "chart_count": min(10, len(document.get("charts") or [])),
        "charts": [{"id": item.get("id"), "title": item.get("title"), "chart_type": item.get("chart_type")} for item in (document.get("charts") or [])[:10]],
        "operations": ["创建只读 SQLite 数据副本", "注册 Superset Dataset", "创建或更新图表", "更新 Dashboard 布局", "启用嵌入访问"],
        "requires_approval": True, "original_is_immutable": True,
    }


@app.post("/api/v1/integrations/superset/publish", response_model=SupersetPublishResult)
async def publish_to_superset(payload: SupersetPublishRequest, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    actor, membership = await actor_for(session, payload.workspace_id, x_actor_id)
    require(membership, "report.publish")
    dataset = await session.get(Dataset, payload.dataset_id)
    if not dataset or dataset.workspace_id != payload.workspace_id:
        raise HTTPException(404, "数据集不存在或不属于当前工作区")
    report = await session.get(Report, payload.report_id) if payload.report_id else None
    if report and (report.workspace_id != payload.workspace_id or report.dataset_id != dataset.id):
        raise HTTPException(404, "报告不存在或不属于当前数据集")
    if not report:
        frame = read_dataframe(dataset.storage_key)
        document = build_report(frame, dataset.profile or profile_dataframe(frame), f"{dataset.name} 分析报告", "生成 Superset 专业看板", dataset.semantics)
        version = await ensure_dataset_version(session, dataset)
        report = Report(
            workspace_id=payload.workspace_id, project_id=version.project_id,
            dataset_id=dataset.id, dataset_version_id=version.id,
            title=document.title, document=document.model_dump(mode="json"),
        )
        session.add(report)
        await session.flush()
        await record_report_artifact(session, report)
    result = await _perform_superset_publish(
        session=session, actor_id=actor.id, workspace_id=payload.workspace_id, dataset=dataset, report=report,
        title=payload.title or f"{dataset.name} 专业分析看板", allowed_domains=payload.allowed_domains,
    )
    await session.commit()
    return SupersetPublishResult.model_validate(result)


@app.post("/api/v1/integrations/superset/guest-token")
async def issue_superset_guest_token(payload: dict, workspace_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    actor, membership = await actor_for(session, workspace_id, x_actor_id)
    require(membership, "report.view")
    dashboard_id = str(payload.get("dashboard_id", "")).strip()
    if not dashboard_id:
        raise HTTPException(422, "dashboard_id 必填")
    token = await superset_guest_token(dashboard_id, actor.display_name, payload.get("rls") or [])
    return {"token": token, "dashboard_id": dashboard_id}


@app.post("/api/v1/integrations/superset/repair-embed")
async def repair_superset_embed(payload: dict, workspace_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    """Repair stale local browser origins for an existing embedded dashboard."""
    actor, membership = await actor_for(session, workspace_id, x_actor_id)
    require(membership, "report.publish")
    existing = await session.scalar(select(ExternalResource).where(
        ExternalResource.workspace_id == workspace_id, ExternalResource.provider == "superset",
        ExternalResource.resource_type == "dashboard",
    ).order_by(ExternalResource.created_at.desc()))
    dashboard_id = (existing.metadata_json or {}).get("dashboard_id") if existing else None
    if not dashboard_id:
        raise HTTPException(404, "当前工作区没有已发布的 Superset 看板")
    result = await repair_embedded_dashboard(int(dashboard_id), payload.get("allowed_domains"))
    existing.external_id = result["embedded_id"] or existing.external_id
    await audit(session, workspace_id, actor.id, "superset.repair_embed", "dashboard", str(dashboard_id), {"allowed_domains": result["allowed_domains"]})
    await session.commit()
    return result


@app.post("/api/v1/integrations/superset/bootstrap-dashboard")
async def bootstrap_superset_dashboard(payload: dict, workspace_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    actor, membership = await actor_for(session, workspace_id, x_actor_id)
    require(membership, "report.publish")
    existing = await session.scalar(select(ExternalResource).where(ExternalResource.workspace_id == workspace_id, ExternalResource.provider == "superset", ExternalResource.resource_type == "dashboard").order_by(ExternalResource.created_at.desc()))
    if existing:
        return {"dashboard_id": existing.metadata_json.get("dashboard_id"), "embedded_id": existing.external_id, "title": existing.metadata_json.get("title"), "created_by": existing.created_by}
    title = str(payload.get("title") or "Insight Studio 专业看板").strip()[:160]
    domains = normalize_embedded_domains(payload.get("allowed_domains"))
    result = await create_embedded_dashboard(title, domains)
    session.add(ExternalResource(workspace_id=workspace_id, provider="superset", resource_type="dashboard", external_id=str(result["embedded_id"]), metadata_json={"dashboard_id": result["dashboard_id"], "title": result["title"]}, created_by=actor.id))
    await session.commit()
    return {**result, "created_by": actor.id}


@app.get("/api/v1/integrations/superset/resources")
async def superset_resources(workspace_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    _, membership = await actor_for(session, workspace_id, x_actor_id)
    require(membership, "report.view")
    rows = (await session.scalars(select(ExternalResource).where(ExternalResource.workspace_id == workspace_id, ExternalResource.provider == "superset").order_by(ExternalResource.created_at.desc()))).all()
    return [{"id": row.id, "resource_type": row.resource_type, "embedded_id": row.external_id, **(row.metadata_json or {}), "created_at": row.created_at} for row in rows]
