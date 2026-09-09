# Token Center and Analysis Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add trustworthy per-stage token accounting and a configurable, non-repetitive analysis clarification flow without changing the single-machine, no-login experience.

**Architecture:** Extend the existing SQLite models additively, keep provider usage as the only token source of truth, and implement the clarification capability as one repository-owned JSON definition plus deterministic Python orchestration. The current `/api/v1/chat/plans` endpoint remains compatible and returns an optional intake card when execution should pause.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic v2, SQLite, Vue 3, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-05-local-ai-bi-core-upgrade-design.md` sections 4.1, 4.2, 5.1, 5.2, 6, 7 and 8.

## Global Constraints

- Keep single-machine mode login-free; do not add user or team CRUD.
- Never estimate tokens from characters. If a provider omits usage, persist `usage_unavailable=true` and show that fact.
- Retain `estimated_cost_cny` and `pricing` only for backward-compatible database reads; remove money from new UI.
- Store clarification mode per conversation: `auto`, `always`, or `off`; new conversations inherit the application default `auto`.
- Stable question keys are the deduplication identity. A key in `confirmed_keys` or `defaulted_keys` must not be asked again unless the user starts a materially new objective and explicitly clears it.
- Keep skill execution behind typed application code. Do not build a generic plugin engine.
- Run targeted tests after each task and the full regression suite before completion.

---

## Task 1: Persist stage-aware token context

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/database.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_api.py`

- [ ] Add a failing compatibility test that starts with the old `llm_usage_logs`, `projects`, and `conversations` table shapes, runs `ensure_compat_schema`, and asserts all new columns exist.
- [ ] Add nullable/indexed `run_id`, `report_id`, and `dashboard_id` string columns plus `stage`, `purpose`, and `usage_unavailable` to `LlmUsageLog`.
- [ ] Add `analysis_brief: JSON = {}` to `Project` and `clarification_mode: String(16) = "auto"` to `Conversation`.
- [ ] Add the same fields to `ensure_compat_schema`; use additive `ALTER TABLE` only and do not rewrite existing rows.
- [ ] Add response schema fields with defaults so old rows serialize successfully.
- [ ] Run `python -m pytest backend/tests/test_api.py -k "compat_schema or usage" -q`.

Use this exact model contract:

```python
stage: Mapped[str] = mapped_column(String(24), default="unknown", index=True)
run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
report_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
dashboard_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
purpose: Mapped[str] = mapped_column(String(120), default="")
usage_unavailable: Mapped[bool] = mapped_column(Boolean, default=False)
```

Do not add foreign keys for the three usage links in this migration: old SQLite files and object deletion must not invalidate accounting history.

## Task 2: Centralize usage writes and label every model call

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/llm.py`
- Test: `backend/tests/test_api.py`

- [ ] Write a failing test that invokes builtin/fake DeepSeek planning and synthesis responses and asserts separate `planning` and `synthesis` log rows.
- [ ] Change `usage_log` to accept keyword-only `stage`, `purpose`, `run_id`, `report_id`, and `dashboard_id` parameters.
- [ ] Set `usage_unavailable` when the provider response does not contain official usage; leave all token fields at zero.
- [ ] Update every `complete(...)` call site and use one of the closed stage values: `intake`, `planning`, `synthesis`, `chart`, `report`, `dashboard`.
- [ ] Give each call a concise purpose such as `生成分析计划`, `整理证据结论`, or `生成单图修改方案`.
- [ ] Assert that deterministic report building and local statistics create no usage row and therefore consume `0 模型 Token`.
- [ ] Run `python -m pytest backend/tests/test_api.py -k "usage or chat_plan or chart_proposal" -q`.

The helper signature is:

```python
def usage_log(
    workspace_id: str,
    conversation_id: str | None,
    plan_id: str | None,
    provider: ProviderConfig,
    result: CompletionResult,
    *,
    stage: Literal["intake", "planning", "synthesis", "chart", "report", "dashboard"],
    purpose: str,
    run_id: str | None = None,
    report_id: str | None = None,
    dashboard_id: str | None = None,
) -> LlmUsageLog:
    ...
```

## Task 3: Add Token Center aggregation APIs

**Files:**
- Modify: `backend/app/schemas.py`
- Create: `backend/app/usage.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api.py`

- [ ] Add failing tests for `range=today`, `range=7d`, and `range=all`, including multiple stages and a provider row with unavailable usage.
- [ ] Define `TokenUsageTotals`, `TokenUsageGroup`, `TokenUsageItem`, and `TokenUsageSummary` schemas.
- [ ] Implement a plain SQLAlchemy aggregation function in `usage.py`; do not add an analytics dependency.
- [ ] Add `GET /api/v1/usage/tokens` with `workspace_id`, `range`, and `group_by=stage|model|run|report|dashboard`.
- [ ] Add `GET /api/v1/usage/tokens/runs/{run_id}` and `GET /api/v1/usage/tokens/reports/{report_id}`.
- [ ] Return totals, grouped totals, latest 50 calls, and `unavailable_call_count`; never return `estimated_cost_cny` or `pricing` from these endpoints.
- [ ] Verify `sum(group.total_tokens) == totals.total_tokens` for every non-null grouping dimension.
- [ ] Run `python -m pytest backend/tests/test_api.py -k "token_usage" -q`.

Expected summary shape:

```json
{
  "range": "7d",
  "totals": {
    "prompt_tokens": 1200,
    "cache_hit_tokens": 200,
    "cache_miss_tokens": 1000,
    "completion_tokens": 300,
    "total_tokens": 1500,
    "call_count": 3
  },
  "groups": [{"key": "planning", "total_tokens": 800, "call_count": 1}],
  "unavailable_call_count": 0,
  "latest": []
}
```

## Task 4: Define the repository-owned analysis-intake skill

**Files:**
- Create: `backend/app/skills/analysis-intake.json`
- Create: `backend/app/intake.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_services.py`

- [ ] Add failing unit tests for trigger detection, stable-key deduplication, maximum eight questions, and default assumption recording.
- [ ] Define `ClarificationMode`, `IntakeQuestion`, `AnalysisBrief`, `IntakeDecision`, and brief update schemas.
- [ ] Add the JSON skill definition with `version: "analysis-intake-v1"`, trigger phrases, eight stable question keys, recommended defaults, reasons, and affected outputs.
- [ ] Implement `load_intake_skill()` using `Path(__file__).with_name("skills")`; validate the file at startup and fall back to the same built-in constant if the file is unreadable.
- [ ] Implement `evaluate_intake(message, profile, brief, mode)` deterministically first; it must return `should_pause=false` when mode is `off`.
- [ ] Treat dataset values and user-provided descriptions as untrusted content; they can fill context but cannot alter the question protocol.
- [ ] Run `python -m pytest backend/tests/test_services.py -k "intake" -q`.

Required keys and defaults:

```python
DEFAULTS = {
    "audience": "业务负责人",
    "decision": "识别趋势、结构与异常，并给出可验证建议",
    "time_range": "使用数据中全部可靠时间范围",
    "comparison": "与上一可靠周期及总体平均比较",
    "metric_definition": "使用原字段名和本地聚合口径",
    "unit_currency": "沿用数据源单位，未知时明确标注",
    "targets": "无已确认目标值，仅做描述性比较",
    "output": "可编辑专业报告",
}
```

## Task 5: Expose project brief and conversation mode APIs

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api.py`

- [ ] Add failing API tests for getting an empty brief, asking all gaps once, answering selected questions, applying all defaults, and not asking resolved keys again.
- [ ] Add `GET /api/v1/projects/{project_id}/brief` and `PUT /api/v1/projects/{project_id}/brief`; verify the project belongs to `workspace_id`.
- [ ] Add `POST /api/v1/projects/{project_id}/brief/questions` accepting `conversation_id`, `dataset_id`, `objective`, and optional requested mode.
- [ ] Extend `ConversationUpdate` with `clarification_mode` and persist it through the existing conversation update endpoint.
- [ ] On “use defaults”, merge only unanswered returned keys into `answers`, append them to `defaulted_keys`, and never append them to `confirmed_keys`.
- [ ] Persist `asked_keys`, skill version, `objective_fingerprint`, and `updated_at` in `Project.analysis_brief`.
- [ ] Run `python -m pytest backend/tests/test_api.py -k "brief or clarification" -q`.

The fingerprint is `sha256(normalize(objective) + sorted(dataset field names))`; it is not computed from raw row values.

## Task 6: Integrate intake with chat planning without breaking clients

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/prompting.py`
- Test: `backend/tests/test_api.py`

- [ ] Extend `ChatPlanResult` with optional `intake: IntakeDecision | None = None`; existing fields remain unchanged.
- [ ] Add failing tests showing `auto` pauses for report/dashboard/complex-analysis gaps, `always` checks every request without repeating keys, and `off` immediately returns a plan.
- [ ] Before model planning, evaluate intake using the selected conversation mode and saved project brief.
- [ ] If `should_pause`, persist the user message with `message_meta.intake`, return it, and do not call the planning model.
- [ ] If no pause is required, pass a compact brief packet to `planner_prompt`: confirmed answers, default assumptions, reliable date precision, and output type only.
- [ ] Add `defaulted_keys` to generated report metadata and a visible “未经确认的业务假设” block when any exist.
- [ ] Record an `intake` usage row only if a later optional model refinement call actually occurs; deterministic intake costs zero model tokens.
- [ ] Run `python -m pytest backend/tests/test_api.py -k "chat_plan and intake" -q`.

## Task 7: Build the Token Center and clarification UI

**Files:**
- Create: `frontend/src/api/usage.js`
- Create: `frontend/src/api/intake.js`
- Create: `frontend/src/components/TokenCenter.vue`
- Create: `frontend/src/components/AnalysisIntakeCard.vue`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/style.css`

- [ ] Add a `Token 中心` settings/page route that loads range totals, stage groups, and latest calls.
- [ ] Render unavailable usage as `服务商未返回 Token` and deterministic operations as `0 模型 Token`; do not render currency.
- [ ] Place a compact clarification menu next to the existing permission menu in the composer with `自动`, `每次检查`, and `关闭`.
- [ ] Persist menu changes immediately through the conversation API and restore the value after refresh.
- [ ] Render all returned questions in one `AnalysisIntakeCard`, with per-question input, recommended default, reason, and affected outputs.
- [ ] Add `使用推荐默认值继续` and `提交并继续` actions; both call the brief API and then re-submit the original objective once.
- [ ] Show the state label `自动`, `N 项待回答`, `已完成`, or `已关闭` without adding repeated chat bubbles.
- [ ] Remove the old money estimate from the composer usage strip while retaining input/output/cache token counts.
- [ ] Run `npm run build` from `frontend`.

## Task 8: End-to-end regression and documentation

**Files:**
- Modify: `frontend/scripts/run-e2e.mjs`
- Modify: `README.md`
- Modify: `docs/requirements-vnext.md`
- Modify: `docs/detailed-design-vnext.md`

- [ ] Add a Playwright flow that creates a conversation, selects each clarification mode, refreshes, and verifies persistence.
- [ ] In auto mode, request a report, answer one field, accept defaults for the rest, and verify the report shows unconfirmed assumptions.
- [ ] Open Token Center and verify planning and synthesis rows are distinct and totals equal their sum.
- [ ] Run `python -m pytest backend/tests -q`.
- [ ] Run `npm run build` and `npm run test:e2e` from `frontend`.
- [ ] Update the user-facing docs with token semantics, the three clarification modes, and the no-money policy.
- [ ] Run `rg -n "T.B.D|T.O.D.O|估算费用|estimated_cost" docs frontend/src/components/TokenCenter.vue frontend/src/components/AnalysisIntakeCard.vue` and resolve user-facing leftovers.
- [ ] Run `git diff --check` and review only files named in this plan before committing.

## Acceptance Gate

- [ ] Provider-reported token totals are traceable by stage and related object.
- [ ] Missing provider usage is never fabricated.
- [ ] First clarification presents all relevant questions in one card and never exceeds eight.
- [ ] Resolved/defaulted questions do not repeat within the same objective.
- [ ] Reports clearly expose every unconfirmed default assumption.
- [ ] Existing chat, analysis, chart editing, report export, and no-login startup tests still pass.
