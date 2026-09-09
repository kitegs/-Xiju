"""Approved plan execution. Integrations enter through explicit ports, not app.main."""
from __future__ import annotations
import json
import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import DAILY_LLM_BUDGET_CNY
from .analysis_modes import describe_statistics, survey_statistics, cleaning_recommendations
from .research import inferential_statistics, survey_cross_analysis
from .forecasting import forecast_time_series, recommendation_actions
from .capabilities import COMPONENT_TOOLS, configure_steps, deepen, attach_deep_analysis, optimize_layout, review as review_content, alternatives as report_alternatives
from .models import Conversation, ChatMessage, Dataset, AnalysisRun, ProviderConfig, Project, Report, ReportTemplate, GeneratedArtifact, McpServer
from .schemas import ChatExecuteRequest, ChatResult, AnalysisPlan, AnalysisOptions, CleaningStep, AnalysisBrief, ChartSpec, ReportBlock, ReportDocument, Evidence
from .policy import enforce_tools, ToolPolicyError
from .team import actor_for, require, audit
from .commercial import ensure_dataset_version, record_report_artifact
from .intake import apply_brief_to_report
from .services import read_dataframe, profile_dataframe, quality_summary, normalize_sql_columns, validate_non_additive_sql, run_sql_query, storage_path, build_report, assess_report_quality
from .report_claims import seal_claims
from .report_templates import render_docx_template
from .sandbox import run_generated_python_async
from .mcp_client import call_tool as call_mcp_tool
from .prompting import PROMPT_VERSIONS, synthesis_context, synthesis_prompt, validate_synthesis, render_synthesis, fallback_synthesis, parse_json_object as _extract_json_object
from .presenters import as_artifact, as_message
from .run_runtime import RunCancelled
from .domain import validate_execution_snapshot
from .fact_catalog import fact_catalog, fact_summary_prompt, validate_fact_summary
from .report_requirements import resolve_requirements, compose_report
from .result_presentation import unique_evidence_for_summary
from . import delivery

@dataclass(frozen=True)
class ExecutionPorts:
    complete: Callable
    enforce_llm_budget: Callable
    usage_log: Callable
    create_cleaned_copy: Callable
    publish_superset: Callable
    append_event: Callable

async def execute_plan(payload: ChatExecuteRequest, actor_id: str | None, session: AsyncSession, run_id: str | None = None, *, ports: ExecutionPorts) -> ChatResult:
    complete = ports.complete
    enforce_llm_budget = ports.enforce_llm_budget
    usage_log = ports.usage_log
    _create_cleaned_copy = ports.create_cleaned_copy
    _perform_superset_publish = ports.publish_superset
    _append_run_event = ports.append_event

    conversation = await session.get(Conversation, payload.conversation_id)
    user_message = await session.get(ChatMessage, payload.plan_message_id)
    if not conversation or conversation.workspace_id != payload.workspace_id or not user_message or user_message.conversation_id != conversation.id:
        raise HTTPException(404, "分析计划不存在或不属于当前工作区")
    user_meta = dict(user_message.message_meta or {})
    plan = AnalysisPlan.model_validate(user_meta.get("analysis_plan") or {})
    capability_settings = AnalysisOptions.model_validate(user_meta.get("analysis_options") or {}).capabilities
    expected_components = {step.tool for step in configure_steps(plan.steps, capability_settings, bool(plan.dataset_id)) if step.tool in COMPONENT_TOOLS}
    if any(step.tool in COMPONENT_TOOLS and step.tool not in expected_components for step in plan.steps):
        raise HTTPException(403, "计划包含已关闭的分析组件，请重新生成计划")
    if plan.status != "pending":
        raise HTTPException(409, "该计划已执行或已取消")
    try:
        enforce_tools(plan.execution_mode, [step.tool for step in plan.steps], approved=payload.approved)
    except ToolPolicyError as exc:
        raise HTTPException(403 if "禁止" in str(exc) else 409, str(exc)) from exc
    actor, membership = await actor_for(session, payload.workspace_id, actor_id)
    require(membership, "analysis.execute")

    dataset = await session.get(Dataset, plan.dataset_id) if plan.dataset_id else None
    if plan.dataset_id and dataset is None:
        raise HTTPException(404, "计划引用的数据集已不存在")
    if dataset and dataset.workspace_id != payload.workspace_id:
        raise HTTPException(404, "数据集不存在或不属于当前工作区")
    dataset_version = await ensure_dataset_version(session, dataset) if dataset else None
    if run_id:
        pinned_run = await session.get(AnalysisRun, run_id)
        if not pinned_run or pinned_run.workspace_id != payload.workspace_id or pinned_run.plan_message_id != payload.plan_message_id:
            raise HTTPException(409, "运行记录与计划不匹配")
        try:
            validate_execution_snapshot(pinned_run.analysis_spec or {}, plan.model_dump(mode="json"),
                                        pinned_run.dataset_version_ids or [], dataset_version.id if dataset_version else None)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
    if dataset:
        conversation.project_id = dataset.project_id
    plan.status = "running"
    user_meta = {**user_meta, "analysis_plan": plan.model_dump(mode="json")}
    user_message.message_meta = user_meta
    await session.flush()

    frame = None
    profile = dataset.profile if dataset else {}
    quality = None
    report_id = None
    report = None
    tool_runs: list[dict] = []
    evidence: list[dict] = []
    provider_name = "builtin"
    usage_meta = None
    professional_result = None
    forecast_result = None
    recommendations: list[dict] = []
    template_artifact = None
    claims_meta = None
    synthesis_validation = None
    component_results = []
    component_usage = {"calls": 0, "total_tokens": 0, "unavailable": False}

    async def component_ask(component, instruction, packet):
        provider = await session.scalar(select(ProviderConfig).where(
            ProviderConfig.workspace_id == payload.workspace_id,
            ProviderConfig.enabled.is_(True), ProviderConfig.encrypted_api_key != "",
        ).order_by(ProviderConfig.is_default.desc(), ProviderConfig.updated_at.desc()).limit(1))
        if not provider:
            return None
        await enforce_llm_budget(session, payload.workspace_id)
        completion = await complete(provider, [{"role": "user", "content": instruction}],
            "INPUT\n" + json.dumps(packet, ensure_ascii=False, default=str),
            request_options={"thinking": {"type": "disabled"}, "response_format": {"type": "json_object"}, "max_tokens": 1200})
        row = usage_log(payload.workspace_id, conversation.id, plan.id, provider, completion,
            stage="planning" if component == "deep_analysis" else "report",
            purpose=f"component:{component}", run_id=run_id, report_id=report_id)
        session.add(row)
        component_usage["calls"] += 1
        component_usage["total_tokens"] += row.total_tokens
        component_usage["unavailable"] = component_usage["unavailable"] or row.usage_unavailable
        await session.flush()
        # Preserve official usage even if schema validation of the answer fails.
        await session.commit()
        return completion.content

    try:
        for step in plan.steps:
            if run_id:
                cancellation_requested = await session.scalar(select(AnalysisRun.cancel_requested).where(AnalysisRun.id == run_id))
                if cancellation_requested:
                    raise RunCancelled("用户取消了该运行")
                run = await session.get(AnalysisRun, run_id)
                if run:
                    run.progress = {"current_step": step.id, "title": step.title, "completed_steps": len(tool_runs), "total_steps": len(plan.steps)}
                    await _append_run_event(
                        session, run_id, "step.started", "running", step.title,
                        step_id=step.id, data={"tool": step.tool, "completed_steps": len(tool_runs), "total_steps": len(plan.steps)},
                    )
                    await session.commit()
            started = time.perf_counter()
            input_summary = ""
            output_summary = ""
            evidence_ids: list[str] = []
            step_status = "completed"
            if step.tool == "dataset.profile" and dataset:
                frame = frame if frame is not None else read_dataframe(dataset.storage_key)
                profile = profile_dataframe(frame)
                if dataset.profile != profile:
                    dataset.profile = profile
                columns = [item.get("name") for item in profile.get("columns", [])]
                input_summary = f"数据集：{dataset.name}"
                output_summary = f"{profile.get('row_count', 0):,} 行、{profile.get('column_count', 0)} 列；字段：{', '.join(columns[:8])}"
                evidence.append({
                    "id": "dataset-shape", "statement": f"数据集包含 {profile.get('row_count', 0):,} 行、{profile.get('column_count', 0)} 列。",
                    "method": "读取导入时保存的数据画像", "value": f"{profile.get('row_count', 0)} rows × {profile.get('column_count', 0)} columns", "source_columns": [],
                })
                evidence_ids = ["dataset-shape"]
            elif step.tool == "data.quality" and dataset:
                frame = frame if frame is not None else read_dataframe(dataset.storage_key)
                quality = quality_summary(frame)
                input_summary = f"扫描 {len(frame):,} 行 × {len(frame.columns)} 列"
                output_summary = f"质量评分 {quality.score}/100；缺失 {quality.missing_cells}；重复 {quality.duplicate_rows}"
                evidence.append({
                    "id": "quality-summary", "statement": output_summary,
                    "method": "全表缺失值、完全重复行与文本空格检查", "value": f"score={quality.score}; missing={quality.missing_cells}; duplicates={quality.duplicate_rows}",
                    "source_columns": [str(column) for column in frame.columns],
                })
                evidence_ids = ["quality-summary"]
            elif step.tool == "statistics.describe" and dataset:
                frame = frame if frame is not None else read_dataframe(dataset.storage_key)
                statistical_evidence = describe_statistics(frame)
                evidence.extend(statistical_evidence)
                input_summary = f"对 {len(frame):,} 行数据的数值字段计算描述统计"
                output_summary = f"生成 {len(statistical_evidence)} 组可复核描述统计与置信区间"
                evidence_ids = [item["id"] for item in statistical_evidence]
            elif step.tool == "research.inferential" and dataset:
                frame = frame if frame is not None else read_dataframe(dataset.storage_key)
                research_evidence = inferential_statistics(frame, semantics=dataset.semantics)
                evidence.extend(research_evidence)
                input_summary = f"根据 {len(frame):,} 行数据的字段类型自动选择推断统计方法"
                output_summary = f"生成 {len(research_evidence)} 条 t 检验、ANOVA、卡方、回归或样本量证据"
                evidence_ids = [item["id"] for item in research_evidence]
            elif step.tool == "survey.profile" and dataset:
                frame = frame if frame is not None else read_dataframe(dataset.storage_key)
                survey_evidence = survey_statistics(frame)
                evidence.extend(survey_evidence)
                input_summary = f"扫描 {len(frame.columns)} 个字段的离散取值和完整作答记录"
                output_summary = f"生成 {len(survey_evidence)} 条问卷结构与信度证据"
                evidence_ids = [item["id"] for item in survey_evidence]
            elif step.tool == "survey.cross_analysis" and dataset:
                frame = frame if frame is not None else read_dataframe(dataset.storage_key)
                cross_evidence = survey_cross_analysis(frame)
                evidence.extend(cross_evidence)
                input_summary = f"在 {len(frame):,} 行问卷记录中寻找分组和分类字段"
                output_summary = f"生成 {len(cross_evidence)} 条交叉表、卡方和效应量证据"
                evidence_ids = [item["id"] for item in cross_evidence]
            elif step.tool == "cleaning.recommend" and dataset:
                frame = frame if frame is not None else read_dataframe(dataset.storage_key)
                quality = quality or quality_summary(frame)
                cleaning_evidence = cleaning_recommendations(frame, quality)
                evidence.extend(cleaning_evidence)
                input_summary = f"质量评分 {quality.score}/100；仅生成建议，不修改原始数据"
                output_summary = cleaning_evidence[0]["value"]
                evidence_ids = [item["id"] for item in cleaning_evidence]
            elif step.tool == "data.clean.apply" and dataset:
                raw_steps = step.arguments.get("steps")
                if not isinstance(raw_steps, list) or not raw_steps:
                    raise ValueError("数据副本清洗步骤缺少 arguments.steps")
                cleaning_steps = [CleaningStep.model_validate(item) for item in raw_steps]
                source_dataset = dataset
                dataset, recipe, frame, impact = await _create_cleaned_copy(
                    session, source_dataset, payload.workspace_id,
                    str(step.arguments.get("name") or f"{source_dataset.name} · AI 清洗副本"), cleaning_steps,
                )
                dataset_version = await ensure_dataset_version(session, dataset)
                conversation.dataset_id = dataset.id
                profile = dataset.profile
                quality = None
                evidence_id = f"cleaning-{step.id}"
                evidence.append({
                    "id": evidence_id,
                    "statement": f"已从 {source_dataset.name} 创建清洗后的数据副本 {dataset.name}",
                    "method": "按批准的结构化清洗步骤生成新 Dataset 与 DatasetVersion；原始文件保持不变",
                    "value": f"{impact['before_rows']} 行 → {impact['after_rows']} 行；修改 {impact['changed_cells']} 个单元格",
                    "source_columns": [str(column) for column in frame.columns],
                    "data": impact["step_results"],
                    "code": json.dumps([item.model_dump(mode="json") for item in cleaning_steps], ensure_ascii=False),
                })
                if run_id:
                    run = await session.get(AnalysisRun, run_id)
                    if run:
                        run.dataset_version_ids = list(dict.fromkeys([*(run.dataset_version_ids or []), dataset_version.id]))
                input_summary = f"源数据副本：{source_dataset.name}；{len(cleaning_steps)} 个结构化步骤"
                output_summary = f"创建新数据版本 {dataset_version.id}；原始文件未修改"
                evidence_ids = [evidence_id]
            elif step.tool == "timeseries.forecast" and dataset:
                frame = frame if frame is not None else read_dataframe(dataset.storage_key)
                forecast_result = forecast_time_series(
                    frame, date_column=step.arguments.get("date_column"), target_column=step.arguments.get("target_column"),
                    horizon=step.arguments.get("horizon", 6), frequency=step.arguments.get("frequency", "MS"),
                    aggregate=step.arguments.get("aggregate", "sum"),
                )
                evidence_id = "timeseries-forecast"
                evidence.append({
                    "id": evidence_id, "statement": f"{forecast_result.target_column} {forecast_result.horizon} 个周期预测",
                    "method": f"{forecast_result.frequency} 聚合；候选基线留出集回测后选择 {forecast_result.method}",
                    "value": f"MAE={forecast_result.metrics['mae']}; RMSE={forecast_result.metrics['rmse']}; MAPE={forecast_result.metrics['mape']}%",
                    "source_columns": [forecast_result.date_column, forecast_result.target_column],
                    "data": forecast_result.forecast, "code": forecast_result.code,
                })
                input_summary = f"日期={forecast_result.date_column}；指标={forecast_result.target_column}；{forecast_result.horizon} 个{forecast_result.frequency}周期"
                output_summary = f"选择 {forecast_result.method}；回测 MAE {forecast_result.metrics['mae']}；生成 {len(forecast_result.forecast)} 个预测点与 95% 区间"
                evidence_ids = [evidence_id]
            elif step.tool == "action.recommend" and dataset:
                frame = frame if frame is not None else read_dataframe(dataset.storage_key)
                quality = quality or quality_summary(frame)
                recommendations = recommendation_actions(frame, quality, forecast_result)
                evidence_id = "action-recommendations"
                evidence.append({
                    "id": evidence_id, "statement": "结构化行动建议",
                    "method": "确定性质量规则、预测结果和风险模板；不把相关性表述为因果关系",
                    "value": f"生成 {len(recommendations)} 条可验证建议", "source_columns": [], "data": recommendations,
                    "code": "recommendation_actions(frame, quality, forecast_result)",
                })
                input_summary = "质量扫描 + 已完成的预测证据（如有）"
                output_summary = f"生成 {len(recommendations)} 条带优先级、风险和验证方法的建议"
                evidence_ids = [evidence_id]
            elif step.tool == 'data.reconcile' and dataset:
                from .models import DatasetRelationship, DatasetVersion
                from .result_presentation import reconcile_frames
                relation=await session.scalar(select(DatasetRelationship).where(DatasetRelationship.result_dataset_id==dataset.id,DatasetRelationship.workspace_id==payload.workspace_id))
                if not relation: raise ValueError('当前数据没有可追溯的原表关系，不能完成核对')
                left_version=await session.get(DatasetVersion,relation.left_version_id)
                right_version=await session.get(DatasetVersion,relation.right_version_id)
                if not left_version or not right_version or any(v.workspace_id!=payload.workspace_id for v in (left_version,right_version)):
                    raise ValueError('关系原表版本不可用')
                left=read_dataframe(left_version.storage_key); right=read_dataframe(right_version.storage_key)
                metric=next((c for c in ['cnt','Sales','销售额'] if c in left and c in right),None)
                if not metric: raise ValueError('未确认两侧同口径核对指标，需明确映射')
                record=reconcile_frames(left,right,relation.left_keys,relation.right_keys,metric)
                evidence.append(record); evidence_ids=[record['id']]
                input_summary=f'原表版本 {left_version.id} / {right_version.id}'
                output_summary=record['value']
            elif step.tool == "sql.query" and dataset:
                frame = frame if frame is not None else read_dataframe(dataset.storage_key)
                sql = str(step.arguments.get("sql") or "").strip()
                if not sql:
                    raise ValueError("分析计划中的 SQL 步骤缺少 arguments.sql")
                sql = normalize_sql_columns(sql, frame.columns)
                input_summary = sql[:500]
                try:
                    validate_non_additive_sql(sql, dataset.semantics)
                    from .analysis_semantics import validate_ratio_aggregates
                    validate_ratio_aggregates(sql, frame.columns)
                    columns, rows, row_count, truncated, sql_duration = run_sql_query(frame, sql, 300)
                    evidence_id = f"sql-{step.id}"
                    output_summary = f"DuckDB 返回 {row_count} 行、{len(columns)} 列{'，结果已截断' if truncated else ''}"
                    evidence.append({
                        "id": evidence_id, "statement": step.title, "method": "DuckDB 数据副本只读查询",
                        "value": output_summary, "source_columns": columns, "data": rows[:50], "code": sql, 'truncated':truncated or row_count>50,
                    })
                    evidence_ids = [evidence_id]
                    started = time.perf_counter() - sql_duration / 1000
                except Exception as exc:
                    step_status = "failed"
                    output_summary = f"只读 SQL 未执行，后续确定性报告仍继续：{type(exc).__name__}: {str(exc)[:300]}"
            elif step.tool == "python.run" and dataset:
                code = str(step.arguments.get("code") or "").strip()
                if not code:
                    raise ValueError("分析计划中的 Python 步骤缺少 arguments.code")
                sandbox_result = await run_generated_python_async(
                    code, storage_path(dataset.storage_key), int(step.arguments.get("timeout_seconds", 20)),
                )
                evidence_id = f"python-{step.id}"
                input_summary = code[:500]
                output_summary = (sandbox_result.stdout or sandbox_result.stderr or "代码没有输出")[:800]
                evidence.append({
                    "id": evidence_id, "statement": step.title, "method": "无网络、只读数据挂载的 Python 隔离容器",
                    "value": output_summary, "source_columns": [], "data": [], "code": code,
                })
                evidence_ids = [evidence_id]
            elif step.tool == "report.build" and dataset:
                frame = frame if frame is not None else read_dataframe(dataset.storage_key)
                profile = profile_dataframe(frame)
                document = build_report(frame, profile, f"{dataset.name} 分析报告", user_message.content, dataset.semantics)
                project = await session.get(Project, dataset_version.project_id)
                document = apply_brief_to_report(document, AnalysisBrief.model_validate(project.analysis_brief or {}))
                document.metadata["recommendations"] = recommendations
                if forecast_result:
                    forecast_chart = ChartSpec(**{
                        "id": "forecast-line", "title": f"{forecast_result.target_column} 预测", "chart_type": "line",
                        "x": {"column": "date"}, "y": {"column": "forecast", "aggregate": None},
                        "series": [{"column": "forecast", "aggregate": None}], "description": "包含回测选择的基线预测；请结合预测区间和限制使用。",
                        "data": forecast_result.forecast, "evidence_ids": ["timeseries-forecast"],
                        "position": {"x": 0, "y": 0, "w": 12, "h": 5}, "style": {"palette": "business", "show_legend": True, "show_labels": False, "number_format": "auto", "height": 340},
                    })
                    document.charts.append(forecast_chart)
                    document.blocks.extend([
                        ReportBlock(id="forecast-title", kind="heading", content="趋势预测", evidence_ids=[]),
                        ReportBlock(id="forecast-chart", kind="chart", chart_id="forecast-line", evidence_ids=["timeseries-forecast"]),
                    ])
                if recommendations:
                    document.blocks.append(ReportBlock(id="recommendations", kind="callout", content="行动建议：" + "；".join(item["recommendation"] for item in recommendations), evidence_ids=["action-recommendations"]))
                deep_records = [item for item in evidence if str(item.get("id", "")).startswith("deep-")]
                attach_deep_analysis(document, deep_records)
                # Fixed-tool appendices belong to the same generation/evidence boundary.
                extra_ids = ({'action-recommendations'} if recommendations else set()) | ({'timeseries-forecast'} if forecast_result else set())
                document.evidence.extend(Evidence.model_validate(item) for item in evidence if item['id'] in extra_ids and item['id'] not in {known.id for known in document.evidence})
                compose_report(document, frame, resolve_requirements(user_message.content, plan.report_requirements.model_dump()), evidence)
                seal_claims(document)
                document.quality = assess_report_quality(document)
                document.metadata['execution_outcome']={'status':'degraded','problems':[],'note':'运行尚未完整提交；这是中间草稿'}
                document.quality=assess_report_quality(document)
                stable_id=delivery.report_identity(user_message.id)
                report=await session.get(Report,stable_id)
                if report is None:
                    report = Report(id=stable_id,
                    workspace_id=payload.workspace_id, project_id=dataset_version.project_id,
                    dataset_id=dataset.id, dataset_version_id=dataset_version.id, run_id=run_id,
                    title=document.title, document=document.model_dump(mode="json"),
                    )
                else:
                    report.document=document.model_dump(mode='json'); report.title=document.title; report.run_id=run_id
                session.add(report)
                await session.flush()
                report_id = report.id
                if run_id:
                    current_run=await session.get(AnalysisRun,run_id)
                    current_run.report_id=report_id
                await delivery.checkpoint('report-flushed')
                input_summary = f"目标：{user_message.content[:80]}"
                output_summary = f"生成 {len(document.charts)} 个图表、{len(document.blocks)} 个内容块、{len(document.evidence)} 条报告证据"
                report_evidence = [item.model_dump(mode="json") for item in document.evidence]
                from .result_presentation import merge_report_evidence
                merge_report_evidence(evidence, report_evidence)
                evidence_ids = [item["id"] for item in report_evidence]
            elif step.tool == "report.template.fill" and dataset:
                require(membership, "template.use")
                template_id = str(step.arguments.get("template_id") or "")
                template = await session.get(ReportTemplate, template_id)
                if not template or template.workspace_id != payload.workspace_id:
                    raise ValueError("未找到可用的 Word 模板")
                if report is None:
                    raise ValueError("填充模板前必须先生成报告")
                rendered, render_meta = render_docx_template(storage_path(template.storage_key), report)
                artifact_key = f"workspaces/{payload.workspace_id}/artifacts/{uuid4().hex}.docx"
                artifact_path = storage_path(artifact_key); artifact_path.parent.mkdir(parents=True, exist_ok=True); artifact_path.write_bytes(rendered)
                template_artifact = GeneratedArtifact(
                    workspace_id=payload.workspace_id, report_id=report.id, kind="docx-template", name=f"{report.title} - {template.name}.docx",
                    storage_key=artifact_key, metadata_json={"template_id": template.id, **render_meta}, created_by=actor.id,
                )
                session.add(template_artifact); await session.flush()
                input_summary = f"模板：{template.name}；占位符 {len(template.placeholders or [])} 个"
                output_summary = f"已填充 {len(render_meta['filled'])} 个占位符；未填充 {len(render_meta['unresolved'])} 个"
                evidence_id = "template-render"
                evidence.append({"id": evidence_id, "statement": "Word 模板已填充", "method": "安全 DOCX 解析与确定性替换", "value": output_summary, "source_columns": [], "data": [], "code": "report.template.fill"})
                evidence_ids = [evidence_id]
            elif step.tool == "superset.publish" and dataset:
                actor, membership = await actor_for(session, payload.workspace_id, actor_id)
                require(membership, "report.publish")
                frame = frame if frame is not None else read_dataframe(dataset.storage_key)
                if report is None:
                    profile = profile_dataframe(frame)
                    document = build_report(frame, profile, f"{dataset.name} 分析报告", user_message.content, dataset.semantics)
                    project = await session.get(Project, dataset_version.project_id)
                    document = apply_brief_to_report(document, AnalysisBrief.model_validate(project.analysis_brief or {}))
                    report = Report(
                        workspace_id=payload.workspace_id, project_id=dataset_version.project_id,
                        dataset_id=dataset.id, dataset_version_id=dataset_version.id, run_id=run_id,
                        title=document.title, document=document.model_dump(mode="json"),
                    )
                    session.add(report)
                    await session.flush()
                    report_id = report.id
                professional_result = await _perform_superset_publish(
                    session=session, actor_id=actor.id, workspace_id=payload.workspace_id, dataset=dataset,
                    report=report, title=f"{dataset.name} 专业分析看板",
                    allowed_domains=["http://localhost:5174", "http://localhost:5175"], frame=frame,
                )
                input_summary = f"数据副本：{dataset.name}；报告图表：{len((report.document or {}).get('charts', []))}"
                output_summary = f"已发布 {len(professional_result['charts'])} 个图表到 Superset 看板 {professional_result['dashboard_id']}"
                evidence_id = "superset-publish"
                evidence.append({
                    "id": evidence_id, "statement": "专业看板已发布", "method": "Superset REST API + 只读数据副本",
                    "value": output_summary, "source_columns": [], "data": [], "code": professional_result["dashboard_url"],
                })
                evidence_ids = [evidence_id]
            elif step.tool == "mcp.call":
                require(membership, "report.publish")
                server_id = str(step.arguments.get("server_id") or "")
                tool_name = str(step.arguments.get("tool_name") or "")
                tool_arguments = step.arguments.get("arguments") if isinstance(step.arguments.get("arguments"), dict) else {}
                server = await session.get(McpServer, server_id)
                if not server or server.workspace_id != payload.workspace_id or not server.enabled:
                    raise ValueError("MCP 服务不存在、未启用或不属于当前工作区")
                cached_tools = (server.tool_cache or {}).get("tools") or []
                cached_names = {str(item.get("name")) for item in cached_tools if isinstance(item, dict)}
                if not tool_name or tool_name not in cached_names:
                    raise ValueError("MCP 工具未发现；请先在设置中测试并发现该服务的工具")
                if plan.execution_mode == "full" and not server.tool_allowlist:
                    raise ValueError("副本完全访问模式只允许显式加入白名单的 MCP 工具")
                if server.tool_allowlist and tool_name not in set(server.tool_allowlist):
                    raise ValueError("该 MCP 工具不在当前服务的允许清单中")
                mcp_result, mcp_duration = await call_mcp_tool(server, tool_name, tool_arguments)
                evidence_id = f"mcp-{step.id}"
                rendered = json.dumps(mcp_result, ensure_ascii=False, default=str)[:12_000]
                input_summary = f"{server.name} · {tool_name} · {json.dumps(tool_arguments, ensure_ascii=False)[:500]}"
                output_summary = rendered[:900]
                evidence.append({
                    "id": evidence_id, "statement": f"MCP 工具 {server.name}/{tool_name} 已执行",
                    "method": "通过已登记的 MCP Streamable HTTP 服务调用；参数和结果保留在运行证据中",
                    "value": output_summary, "source_columns": [], "data": [{"result": mcp_result}],
                    "code": f"mcp.call({server.id}, {tool_name}, {json.dumps(tool_arguments, ensure_ascii=False)})",
                })
                evidence_ids = [evidence_id]
                started = time.perf_counter() - mcp_duration / 1000
                await audit(session, payload.workspace_id, actor.id, "mcp.tool.call", "mcp_server", server.id, {"tool": tool_name, "plan_id": plan.id})
            elif step.tool in COMPONENT_TOOLS:
                input_summary = "任务创建时保存的分析能力配置"
                component_usage = {"calls": 0, "total_tokens": 0, "unavailable": False}
                component_result = {"tool": step.tool, "status": "completed"}
                try:
                    if step.tool == "analysis.deepen" and dataset:
                        frame = frame if frame is not None else read_dataframe(dataset.storage_key)
                        extra, details = await deepen(frame, user_message.content, evidence,
                            capability_settings.max_rounds, [item["tool"] for item in tool_runs], component_ask,
                            semantics=dataset.semantics, requirements=resolve_requirements(user_message.content, plan.report_requirements.model_dump()))
                        evidence.extend(extra)
                        evidence_ids = [item["id"] for item in extra]
                    elif report:
                        document = ReportDocument.model_validate(report.document)
                        if step.tool == "report.layout":
                            from .extensions import execute_builtin
                            details = execute_builtin(step.tool, document, enabled=capability_settings.chart_layout)
                        elif step.tool == "report.review":
                            details = await review_content(document, user_message.content, component_ask)
                        else:
                            details = report_alternatives(document)
                        document.quality = assess_report_quality(document)
                        report.document = document.model_dump(mode="json")
                    else:
                        details = {"note": "没有可处理的数据或报告"}
                        component_result["status"] = "skipped"
                    component_result["result"] = details
                except Exception as exc:
                    component_result.update(status="failed", error=f"{type(exc).__name__}: {str(exc)[:300]}")
                component_result["usage"] = dict(component_usage)
                component_results.append(component_result)
                output_summary = json.dumps(component_result, ensure_ascii=False, default=str)[:1000]
            elif step.tool == "assistant.synthesize":
                context = synthesis_context(
                    objective=user_message.content, evidence=evidence, report_id=report_id,
                    dashboard_url=professional_result.get("dashboard_url") if professional_result else None,
                )
                provider = await session.scalar(
                    select(ProviderConfig).where(
                        ProviderConfig.workspace_id == payload.workspace_id,
                        ProviderConfig.enabled.is_(True), ProviderConfig.encrypted_api_key != "",
                    ).order_by(ProviderConfig.is_default.desc(), ProviderConfig.updated_at.desc()).limit(1)
                )
                input_summary = f"当前目标 + {min(len(evidence), 60)} 条压缩证据"
                if provider:
                    spent_before = await enforce_llm_budget(session, payload.workspace_id)
                    completion = None
                    try:
                        completion = await complete(
                            provider, [{"role": "user", "content": fact_summary_prompt(strict=True)}], json.dumps({'objective':user_message.content, 'facts':list(fact_catalog(unique_evidence_for_summary(evidence)).values())[:30], 'failed_steps':[r for r in tool_runs if r['status']=='failed']},ensure_ascii=False),
                            request_options={"thinking": {"type": "disabled"}, "response_format": {"type": "json_object"}, "max_tokens": 1800},
                        )
                        # A rejected structured response still consumed model tokens.
                        session.add(usage_log(
                            payload.workspace_id, conversation.id, plan.id, provider, completion,
                            stage="synthesis", purpose="整理运行证据结论", run_id=run_id,
                            report_id=report_id,
                        ))
                        usage_meta = {**completion.as_meta(), "daily_spend_before_cny": round(spent_before, 8), "daily_budget_cny": DAILY_LLM_BUDGET_CNY}
                        structured = validate_fact_summary(_extract_json_object(completion.content), unique_evidence_for_summary(evidence), strict=True)
                        assistant_text = render_synthesis(structured)
                        claims_meta = structured.model_dump(mode="json")
                        synthesis_validation = {"status": "partial" if structured.rejected_claims else "verified", "rejected_claims": structured.rejected_claims, "request_id": completion.request_id}
                        provider_name = provider.provider
                        usage_meta = {**completion.as_meta(), "daily_spend_before_cny": round(spent_before, 8), "daily_budget_cny": DAILY_LLM_BUDGET_CNY}
                    except Exception as exc:
                        synthesis_validation = {"status": "degraded", "error": f"{type(exc).__name__}: {str(exc)[:500]}",
                            "raw_response": completion.content[:16000] if completion is not None else None}
                        structured = fallback_synthesis(evidence, provider_error=f"{type(exc).__name__}: {str(exc)[:120]}")
                        assistant_text = render_synthesis(structured)
                        claims_meta = structured.model_dump(mode="json")
                        provider_name = f"{provider.provider}-fallback"
                else:
                    structured = fallback_synthesis(evidence)
                    assistant_text = render_synthesis(structured)
                    claims_meta = structured.model_dump(mode="json")
                output_summary = f"由 {provider_name} 生成答复；统计事实引用 {len({item['id'] for item in evidence})} 条证据"
                evidence_ids = list(dict.fromkeys(item["id"] for item in evidence))
            tool_runs.append({
                "step_id": step.id, "title": step.title, "tool": step.tool, "status": component_result["status"] if step.tool in COMPONENT_TOOLS else step_status,
                "duration_ms": max(1, round((time.perf_counter() - started) * 1000)),
                "input_summary": input_summary, "output_summary": output_summary,
                "evidence_ids": evidence_ids, "code": next((item.get("code", "") for item in evidence if item.get("id") in evidence_ids and item.get("code")), ""),
                "data_version": dataset_version.id if dataset_version else None,
            })
            if run_id:
                run = await session.get(AnalysisRun, run_id)
                if run:
                    run.progress = {
                        "current_step": step.id, "title": step.title,
                        "completed_steps": len(tool_runs), "total_steps": len(plan.steps),
                    }
                    await _append_run_event(
                        session, run_id, "step.completed", "running", output_summary,
                        step_id=step.id, data={"tool": step.tool, "evidence_ids": evidence_ids, "result_status": tool_runs[-1]["status"],
                            "execution": tool_runs[-1],
                            "evidence": [item for item in evidence if item.get("id") in evidence_ids]},
                    )
                    for evidence_id in evidence_ids:
                        await _append_run_event(
                            session, run_id, "evidence.created", "running", f"已生成证据 {evidence_id}",
                            step_id=step.id, data={"evidence_id": evidence_id},
                        )
                    await session.commit()
    except (RunCancelled, asyncio.CancelledError):
        plan.status = "cancelled"
        user_message.message_meta = {**user_meta, "analysis_plan": plan.model_dump(mode="json")}
        await session.commit()
        raise
    except Exception:
        plan.status = "failed"
        user_message.message_meta = {**user_meta, "analysis_plan": plan.model_dump(mode="json")}
        await session.commit()
        raise

    unique_evidence = list({item["id"]: item for item in evidence}.values())
    from .execution_outcome import assess_outcome
    execution_outcome = assess_outcome(tool_runs, synthesis_validation)
    if execution_outcome['status'] == 'degraded':
        assistant_text = '⚠ 本次运行已结束，但部分工具失败或总结降级；以下内容不是完整验收结论，请展开实际执行记录。\n\n' + assistant_text
    if report:
        document = ReportDocument.model_validate(report.document)
        document.metadata['execution_outcome'] = execution_outcome
        document.metadata["analysis_capabilities"] = capability_settings.model_dump()
        document.metadata["component_results"] = component_results
        document.metadata["synthesis_validation"] = synthesis_validation or {"status": "not_run"}
        document.quality = assess_report_quality(document)
        report.document = document.model_dump(mode="json")
        await record_report_artifact(session, report, run_id=run_id, evidence=unique_evidence)
        await delivery.checkpoint('artifact-flushed')
        if run_id:
            await _append_run_event(
                session, run_id, "artifact.created", "running", f"已生成报告 {report.title}",
                data={"report_id": report.id, "evidence_count": len(unique_evidence)},
            )
    plan.status = "completed"
    user_message.message_meta = {**user_meta, "analysis_plan": plan.model_dump(mode="json")}
    assistant_meta = {
        "dataset_id": dataset.id if dataset else plan.dataset_id, "report_id": report_id, "provider": provider_name,
        "analysis_mode": plan.analysis_mode, "plan_id": plan.id, "tool_runs": tool_runs,
        "evidence": unique_evidence, "usage": usage_meta, "professional_dashboard": professional_result,
        "recommendations": recommendations, "template_artifact": as_artifact(template_artifact).model_dump(mode="json") if template_artifact else None,
        "claims": claims_meta, "prompt_versions": PROMPT_VERSIONS,
        "synthesis_validation": synthesis_validation,
        "execution_outcome": execution_outcome,
        "component_results": component_results, "analysis_capabilities": capability_settings.model_dump(),
    }
    assistant_message = ChatMessage(conversation_id=conversation.id, role="assistant", content=assistant_text, message_meta=assistant_meta)
    session.add(assistant_message)
    conversation.updated_at = datetime.now(timezone.utc)
    await session.flush()
    if run_id:
        from .domain import transition_run
        current_run=await session.get(AnalysisRun,run_id)
        if current_run.cancel_requested:
            raise RunCancelled('提交前收到取消请求')
        transition_run(current_run,'completed')
        current_run.result_message_id=assistant_message.id
        current_run.report_id=report_id
        current_run.finished_at=datetime.now(timezone.utc)
        current_run.progress={**(current_run.progress or {}),'current_step':None,'outcome':execution_outcome['status'],'completed_steps':len(tool_runs)}
        await _append_run_event(session,run_id,'run.completed','completed','运行已结束；请核对交付状态',data={'report_id':report_id,'result_message_id':assistant_message.id,'outcome':execution_outcome['status']})
    await delivery.checkpoint('before-delivery-commit')
    await session.commit()
    await delivery.checkpoint('after-delivery-commit')
    await session.refresh(user_message)
    await session.refresh(assistant_message)
    return ChatResult(user_message=as_message(user_message), assistant_message=as_message(assistant_message), report_id=report_id, provider=provider_name)
