# Whole-Report AI PatchSet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users ask AI to add, remove, rewrite, reorder, and restyle an entire report while guaranteeing reviewable diffs, deterministic data recomputation, quality checks, explicit approval, and versioned rollback.

**Architecture:** Introduce a closed, typed ReportPatchSet and persistent proposal record. The model proposes structure and bindings only; the server validates references, recomputes chart data from the report's DatasetVersion, computes before/after quality, and applies atomically only when the proposal base version is current and the user explicitly approves it.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic v2, Pandas/DuckDB, existing LLM provider adapter, Vue 3, ECharts, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-05-local-ai-bi-core-upgrade-design.md` sections 4.5, 5.3, 6, 7 and 8.1.

## Global Constraints

- Preserve the existing single-chart proposal API and behavior.
- Never accept arbitrary JSON Patch, JavaScript, HTML, SQL, renderer configuration, or chart data from the model.
- All chart values are recomputed from the immutable report DatasetVersion.
- Every proposal follows `generate -> preview/diff -> quality gate -> explicit approve -> versioned save`.
- A stale base version returns HTTP 409 and cannot be force-applied silently.
- An operation producing dangling chart/evidence references or an error-level quality issue cannot be applied.
- Applying a patch is one transaction and creates exactly one ReportVersion.

---

## Task 1: Define the closed ReportPatchSet schema

**Files:**
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_services.py`

- [ ] Add failing schema tests for every allowed operation and for forbidden raw data, arbitrary options, unknown IDs, and invalid positions.
- [ ] Define `ReportPatchOperation`, `ReportPatchSet`, `ReportPatchDiff`, `ReportPatchPreview`, and proposal request/response schemas.
- [ ] Use a discriminated union on `op`; each operation exposes only its own typed payload.
- [ ] Reuse `ChartPatch` for chart updates and define `NewChartSpec` without `data` or `evidence_ids`.
- [ ] Limit a proposal to 30 operations, four series per chart, 2,000 characters per instruction, and 3,000 characters per text block.
- [ ] Run `python -m pytest backend/tests/test_services.py -k "report_patch_schema" -q`.

Allowed discriminators:

```python
ReportPatchOp = Annotated[
    UpdateReportOp
    | AddBlockOp | UpdateBlockOp | DeleteBlockOp | MoveBlockOp
    | AddChartOp | UpdateChartOp | DeleteChartOp | MoveChartOp
    | AddPageBreakOp,
    Field(discriminator="op"),
]
```

`UpdateReportOp` may change only `title`, `summary`, `theme`, and `page_settings`. `AddChartOp` may submit `title`, `chart_type`, field bindings, filters, sort, limit, description, style, and position.

## Task 2: Persist proposals and establish canonical report versions

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/database.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_api.py`

- [ ] Add a failing compatibility migration test for a new `report_patch_proposals` table.
- [ ] Add `ReportPatchProposal` with workspace/project/report/dataset-version links, `base_version`, instruction, patchset JSON, diff JSON, before/after quality JSON, usage JSON, status, and timestamps.
- [ ] Use statuses `pending`, `applied`, `rejected`, and `stale`; default to `pending`.
- [ ] Add `canonical_report_version(document)` as SHA-256 of sorted, UTF-8 JSON and use the same helper in existing chart patch code.
- [ ] Store the base ReportVersion ID when available and always store the canonical content hash used for concurrency checks.
- [ ] Make compatibility creation idempotent for existing SQLite files.
- [ ] Run `python -m pytest backend/tests/test_api.py -k "report_patch_proposal or compat_schema" -q`.

## Task 3: Implement pure PatchSet application and structural validation

**Files:**
- Create: `backend/app/report_patching.py`
- Modify: `backend/app/services.py`
- Test: `backend/tests/test_services.py`

- [ ] Add failing tests for add/update/delete/move block, add/update/delete/move chart, page break, combined operations, and operation ordering.
- [ ] Implement `apply_report_patchset(document, patchset, frame, profile)` as a pure function returning a new ReportDocument, diffs, and computed Evidence.
- [ ] Deep-copy the input document and never mutate the stored object during preview.
- [ ] Resolve target IDs before each operation and return a field-specific validation error for missing or duplicate IDs.
- [ ] Recompute every added/updated chart through the existing chart computation service using validated field names and aggregates.
- [ ] Remove or repair blocks when their chart is deleted; reject deletion when a surviving block still references the chart.
- [ ] Validate that every block, finding, action, and chart evidence ID exists after all operations.
- [ ] Run `python -m pytest backend/tests/test_services.py -k "report_patch_apply" -q`.

The service result is:

```python
@dataclass(frozen=True)
class ReportPatchResult:
    document: ReportDocument
    diffs: list[ReportPatchDiff]
    before_quality: ReportQualityReport
    after_quality: ReportQualityReport
    generated_evidence: list[Evidence]
```

## Task 4: Build compact context and validate model output

**Files:**
- Modify: `backend/app/prompting.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api.py`

- [ ] Add a failing fake-provider test that captures the request and proves raw dataframe rows and full chat history are absent.
- [ ] Add `report_patch_prompt(...)` with prompt version `report-patch-v1` and the exact allowed operation contract.
- [ ] Build a Context Packet containing only AnalysisBrief, report outline, chart bindings, field profile, evidence summaries, quality issues, and the current instruction.
- [ ] Mark user text, dataset labels, and MCP descriptions as untrusted data that cannot override the schema or tool policy.
- [ ] Parse the model response as JSON, validate through `ReportPatchSet`, reject extra fields, and surface a readable validation error.
- [ ] Record stage `report`, purpose `生成整份报告修改方案`, and related report ID in LlmUsageLog.
- [ ] If the provider fails, return a failed proposal response without changing the report.
- [ ] Run `python -m pytest backend/tests/test_api.py -k "report_ai_context or report_ai_invalid" -q`.

## Task 5: Add proposal, preview, apply, and reject APIs

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_api.py`

- [ ] Add `POST /api/v1/reports/{report_id}/ai-proposals` and persist a validated pending proposal.
- [ ] Add `GET /api/v1/reports/{report_id}/ai-proposals/{proposal_id}` with ownership checks.
- [ ] Add `POST /api/v1/reports/{report_id}/ai-proposals/{proposal_id}/preview`, accepting optional disabled operation IDs and returning recomputed diffs and quality.
- [ ] Add `POST /api/v1/reports/{report_id}/ai-proposals/{proposal_id}/apply` requiring `approved: true` and the previewed enabled operation IDs.
- [ ] Add `POST /api/v1/reports/{report_id}/ai-proposals/{proposal_id}/reject` and preserve the audit record.
- [ ] On apply, lock/check the report hash, create a ReportVersion of the previous document, update Report.document once, mark the proposal applied, and commit once.
- [ ] Mark a proposal stale and return 409 when its base hash differs; return 422 when quality contains an error.
- [ ] Run `python -m pytest backend/tests/test_api.py -k "report_ai_proposal" -q`.

## Task 6: Route natural-language whole-report commands correctly

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/prompting.py`
- Test: `backend/tests/test_api.py`

- [ ] Allow `ChatPlanRequest.report_id` without requiring `chart_id`; keep the existing report+chart path for single-chart edits.
- [ ] Add deterministic intent routing for phrases such as `改整份报告`, `增加一节`, `删除图表`, `重新排版`, and `把报告改成` when a current report is selected.
- [ ] Return a report proposal card instead of entering ordinary analysis execution for whole-report edit intent.
- [ ] Do not apply any operation from the chat submit action itself.
- [ ] Include proposal ID, base version, diff summary, quality delta, and usage in message metadata for refresh/recovery.
- [ ] Add a test proving the same instruction without a current report falls back to analysis planning with a helpful selection requirement.
- [ ] Run `python -m pytest backend/tests/test_api.py -k "chat_report_edit" -q`.

## Task 7: Build the whole-report review drawer

**Files:**
- Create: `frontend/src/api/reportProposals.js`
- Create: `frontend/src/components/ReportAiAssistantDrawer.vue`
- Create: `frontend/src/components/ReportPatchDiff.vue`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/style.css`

- [ ] Open the drawer automatically when chat returns a whole-report proposal; keep a manual `AI 修改整份报告` entry in the report toolbar.
- [ ] Show before/after outline, operation list, added/deleted/moved/updated badges, and before/after quality scores.
- [ ] Add an enabled checkbox per operation and call preview whenever the selected set changes; debounce by 250 ms.
- [ ] Render chart previews from server-recomputed data and text changes as readable inline diffs.
- [ ] Disable `确认保存` for stale proposals, pending preview, network errors, or error-level quality issues.
- [ ] Require a final explicit click to apply, then refresh the report and version history exactly once.
- [ ] Provide `拒绝方案` and preserve the current report unchanged.
- [ ] Show proposal token usage; display zero/unavailable accurately and no price.
- [ ] Run `npm run build` from `frontend`.

## Task 8: Regression, concurrency, and rollback verification

**Files:**
- Modify: `frontend/scripts/run-e2e.mjs`
- Modify: `README.md`
- Modify: `docs/requirements-vnext.md`
- Modify: `docs/detailed-design-vnext.md`

- [ ] Add an end-to-end test: ask to add a risk section and move the trend chart, disable one operation, preview, approve, and verify one new report version.
- [ ] Add a stale test: create proposal A, apply a separate manual edit, then assert A cannot apply.
- [ ] Add a rejection test proving document hash and version count stay unchanged.
- [ ] Restore the pre-apply ReportVersion and verify chart data and Evidence references are identical to the original.
- [ ] Run `python -m pytest backend/tests -q`.
- [ ] Run `npm run build` and `npm run test:e2e` from `frontend`.
- [ ] Update docs with the PatchSet lifecycle, allowed operations, failure behavior, and rollback instructions.
- [ ] Run `rg -n "T.B.D|T.O.D.O|raw.*echarts|json patch|直接覆盖" backend/app frontend/src docs` and resolve plan-related unsafe or placeholder paths.
- [ ] Run `git diff --check` and review only files named in this plan before committing.

## Acceptance Gate

- [ ] A natural-language whole-report instruction produces a proposal, never an immediate mutation.
- [ ] Users can inspect and disable individual operations before approval.
- [ ] Chart values are recomputed from the report DatasetVersion and never accepted from model output.
- [ ] Stale or structurally invalid proposals cannot be applied.
- [ ] One approval produces one ReportVersion and rollback restores the previous document.
- [ ] Every resulting factual claim and chart retains valid Evidence references.
- [ ] Existing manual report editing, single-chart AI editing, export, and analysis flows remain functional.
