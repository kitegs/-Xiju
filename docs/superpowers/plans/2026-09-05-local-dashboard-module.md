# Local Multi-Dashboard Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each Project multiple fully local dashboards with CRUD, filters, interactions, revisions, report conversion, and AI layout proposals, while keeping Superset optional.

**Architecture:** Store a validated DashboardDocument snapshot per dashboard and append immutable revisions on every approved mutation. Render with the existing ECharts stack, recompute widget data server-side from the pinned DatasetVersion, and use typed layout PatchSets for AI changes. API routes live in a dedicated router so the root application and `App.vue` stop accumulating unrelated logic.

**Tech Stack:** FastAPI APIRouter, SQLAlchemy async, Pydantic v2, Pandas/DuckDB, Vue 3, ECharts, CSS Grid, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-05-local-ai-bi-core-upgrade-design.md` sections 4.6, 5.4, 6, 7 and 8.

## Global Constraints

- One Project owns zero or more dashboards; no account, member, role, or cloud sharing work is included.
- A dashboard pins a DatasetVersion. Refreshing from a report or newer dataset is an explicit preview-and-confirm action.
- Deletion is soft deletion and must be recoverable.
- Dashboard widget data and filters are validated and computed by the server; never concatenate arbitrary SQL.
- AI layout changes follow proposal, diff, quality, approval, and revision creation.
- Superset is a separate optional publish adapter and is not required for dashboard creation, editing, viewing, or export.
- Use native CSS Grid and pointer events; do not add a dashboard-layout dependency in the first version.

---

## Task 1: Define DashboardDocument and validation rules

**Files:**
- Modify: `backend/app/schemas.py`
- Create: `backend/app/dashboarding.py`
- Test: `backend/tests/test_services.py`

- [ ] Add failing schema tests for valid KPI/chart/table/text/filter widgets and invalid grid bounds, duplicate IDs, unknown fields, and cyclic interactions.
- [ ] Define `DashboardCanvas`, `DashboardFilter`, `DashboardInteraction`, `DashboardWidget`, `DashboardDocument`, and quality schemas.
- [ ] Fix the grid to 12 columns; positions use integer `x`, `y`, `w`, `h`, with `x + w <= 12`, `w >= 1`, and `h >= 1`.
- [ ] Reuse `ChartSpec` bindings for chart widgets but exclude persisted chart `data`; store `source_report_id` and `source_chart_id` separately.
- [ ] Implement `validate_dashboard_document(document, dataset_profile)` and detect overlaps as warnings, not hard errors.
- [ ] Define stable widget/filter/interaction IDs and reject duplicates.
- [ ] Run `python -m pytest backend/tests/test_services.py -k "dashboard_document" -q`.

Minimum document shape:

```json
{
  "version": "1.0",
  "canvas": {"columns": 12, "row_height": 56, "theme": "light"},
  "widgets": [],
  "filters": [],
  "interactions": [],
  "metadata": {"source": "local", "quality": {}}
}
```

## Task 2: Persist dashboards and immutable revisions

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/database.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_api.py`

- [ ] Add failing compatibility tests for fresh creation and repeated startup with `dashboards` and `dashboard_revisions` tables.
- [ ] Add `Dashboard`: workspace/project/dataset-version IDs, title, description, status, document JSON, deleted_at, created_at, and updated_at.
- [ ] Add `DashboardRevision`: dashboard ID, revision number, document JSON, source operation, note, and created_at.
- [ ] Add a unique constraint on `(dashboard_id, revision_number)` and indexes for project/status/deleted_at.
- [ ] Add Pydantic create/update/out/list/revision schemas without user ownership fields.
- [ ] Implement canonical content hashing for optimistic concurrency and expose it as `version_hint`.
- [ ] Run `python -m pytest backend/tests/test_api.py -k "dashboard_schema or compat_schema" -q`.

## Task 3: Add project-scoped Dashboard CRUD

**Files:**
- Create: `backend/app/dashboard_routes.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api.py`

- [ ] Mount an `/api/v1` APIRouter from `dashboard_routes.py`.
- [ ] Add `GET /projects/{project_id}/dashboards` with `include_deleted=false` and verify workspace/project ownership.
- [ ] Add `POST /projects/{project_id}/dashboards`; create revision 1 in the same transaction.
- [ ] Add `GET` and `PATCH /dashboards/{dashboard_id}`; require `base_version` for document changes and create one revision.
- [ ] Add soft `DELETE /dashboards/{dashboard_id}`, `POST /dashboards/{id}/restore`, and `POST /dashboards/{id}/duplicate`.
- [ ] Add `GET /dashboards/{id}/revisions` and `POST /dashboards/{id}/revisions/{revision}/restore`.
- [ ] Verify duplicate copies the document but uses new dashboard/widget IDs and revision 1.
- [ ] Run `python -m pytest backend/tests/test_api.py -k "dashboard_crud or dashboard_revision" -q`.

Required mutation rule:

```python
if payload.base_version != canonical_dashboard_version(dashboard.document):
    raise HTTPException(409, "看板已更新，请刷新后重试")
```

## Task 4: Compute widget data with validated filters

**Files:**
- Modify: `backend/app/dashboarding.py`
- Modify: `backend/app/dashboard_routes.py`
- Test: `backend/tests/test_services.py`
- Test: `backend/tests/test_api.py`

- [ ] Add tests for categorical include/exclude, numeric range, reliable date/year range, Top N, and combined filters.
- [ ] Implement `apply_dashboard_filters(frame, filters, filter_values)` using dataframe masks and schema-validated field names/operators.
- [ ] Reuse existing chart computation for chart/KPI widgets and dataframe row projection for table widgets.
- [ ] Add `POST /dashboards/{dashboard_id}/data-preview` accepting filter values and optional widget IDs.
- [ ] Return widget-local errors without failing unrelated widgets; include rows scanned, rows selected, elapsed time, and DatasetVersion ID.
- [ ] Cap table responses at 500 rows and chart categories at 200 unless a stricter widget limit exists.
- [ ] Reject unknown filter IDs, unknown fields, invalid types, and values outside allowed bounds with HTTP 422.
- [ ] Run `python -m pytest backend/tests -k "dashboard_filter or dashboard_preview" -q`.

## Task 5: Convert a report into an editable local dashboard

**Files:**
- Modify: `backend/app/dashboarding.py`
- Modify: `backend/app/dashboard_routes.py`
- Test: `backend/tests/test_api.py`

- [ ] Add `POST /api/v1/dashboards/from-report/{report_id}` accepting title, selected chart IDs, and `include_findings`.
- [ ] Verify the report has a Project and DatasetVersion; return a clear 422 response otherwise.
- [ ] Convert KPI charts first, then trend, comparison, risk, and table charts into a deterministic non-overlapping grid.
- [ ] Add filter widgets only for useful low-cardinality dimensions and reliable time fields.
- [ ] Copy chart bindings and source IDs but omit chart data so first preview recomputes it.
- [ ] Convert selected report findings into text/callout widgets with evidence IDs.
- [ ] Create dashboard plus revision 1 in one transaction and return a route-ready DashboardOut.
- [ ] Run `python -m pytest backend/tests/test_api.py -k "dashboard_from_report" -q`.

## Task 6: Build the dashboard library and workspace

**Files:**
- Create: `frontend/src/api/dashboards.js`
- Create: `frontend/src/components/DashboardLibrary.vue`
- Create: `frontend/src/components/DashboardWorkspace.vue`
- Create: `frontend/src/components/DashboardWidget.vue`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/style.css`

- [ ] Add `看板` to the primary navigation and hide the existing team navigation entry in single-machine mode.
- [ ] Build a project-scoped library with create, open, rename, duplicate, soft delete, trash view, and restore actions.
- [ ] Build edit, view, and fullscreen modes in `DashboardWorkspace`; use native 12-column CSS Grid.
- [ ] Add widget insert, duplicate, delete, move, resize, title/style edit, and source refresh actions with undo until save.
- [ ] Save all pending changes in one PATCH with `base_version`; on 409 offer reload without discarding the local draft until the user chooses.
- [ ] Add a revision drawer with preview and restore confirmation.
- [ ] Keep filters sticky at the top in view mode and recompute affected widgets through `data-preview`.
- [ ] Run `npm run build` from `frontend`.

## Task 7: Add dashboard interactions and display quality

**Files:**
- Modify: `backend/app/dashboarding.py`
- Modify: `frontend/src/components/DashboardWorkspace.vue`
- Modify: `frontend/src/components/DashboardWidget.vue`
- Modify: `frontend/src/lib/chartOptions.js`
- Test: `frontend/scripts/run-e2e.mjs`

- [ ] Implement filter actions and highlight actions; URL actions and arbitrary scripts remain out of scope.
- [ ] On chart click, map the selected dimension value to declared target widget IDs only.
- [ ] Show active interaction/filter chips and provide `清除筛选` at dashboard scope.
- [ ] Add dashboard quality checks for overlaps, clipped titles, missing units/sources, inaccessible colors, excessive widgets, unreliable dates, and dual-axis risk.
- [ ] Display warnings in edit mode and a compact quality badge in view mode.
- [ ] Add responsive breakpoints that stack widgets on narrow screens without changing persisted desktop positions.
- [ ] Run `npm run test:e2e` from `frontend`.

## Task 8: Add typed AI layout proposals

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/dashboarding.py`
- Modify: `backend/app/dashboard_routes.py`
- Modify: `backend/app/prompting.py`
- Create: `frontend/src/components/DashboardAiAssistantDrawer.vue`
- Test: `backend/tests/test_api.py`

- [ ] Define a closed DashboardPatchSet: update metadata, add/update/delete/move/resize widget, add/update/delete filter, and add/delete interaction.
- [ ] Add `POST /dashboards/{id}/ai-proposals`, `/ai-proposals/{proposal_id}/preview`, `/apply`, and `/reject`.
- [ ] Persist proposals in a `dashboard_patch_proposals` table using the same pending/applied/rejected/stale rules as report proposals.
- [ ] Send only AnalysisBrief, dashboard structure, field profile, widget evidence summaries, and quality issues to the model; never send full rows.
- [ ] Recompute preview data and before/after quality server-side; record stage `dashboard` token usage.
- [ ] Render per-operation toggles, layout before/after miniatures, quality delta, and explicit approve in the AI drawer.
- [ ] Create exactly one DashboardRevision on apply and return 409 for stale proposals.
- [ ] Run `python -m pytest backend/tests/test_api.py -k "dashboard_ai" -q` and `npm run build`.

## Task 9: Golden flow, regression, and documentation

**Files:**
- Modify: `frontend/scripts/run-e2e.mjs`
- Modify: `scripts/verify-commercial-report.py`
- Modify: `README.md`
- Modify: `docs/requirements-vnext.md`
- Modify: `docs/detailed-design-vnext.md`

- [ ] Generate the verified Global Superstore report, then create two dashboards from it: `经营总览` and `利润与折扣风险`.
- [ ] Assert the two dashboards have different IDs, documents, filters, and revision histories under one Project.
- [ ] Exercise create, edit, save, filter, click interaction, duplicate, fullscreen, soft delete, restore, revision restore, and AI layout approval in Playwright.
- [ ] Stop/disable Superset and prove all local Dashboard tests still pass.
- [ ] Run `python -m pytest backend/tests -q`.
- [ ] Run `npm run build` and `npm run test:e2e` from `frontend`.
- [ ] Update screenshots and README instructions for the local workflow; describe Superset only as optional professional publishing.
- [ ] Run `rg -n "T.B.D|T.O.D.O|Superset.*必需|team|用户管理" docs frontend/src/components/Dashboard*.vue backend/app/dashboard*` and resolve scope-conflicting text.
- [ ] Run `git diff --check` and review only files named in this plan before committing.

## Acceptance Gate

- [ ] One Project can own and independently edit multiple dashboards.
- [ ] Dashboard CRUD, duplicate, soft delete, restore, revisions, and optimistic concurrency work in no-login mode.
- [ ] Filters and interactions recompute only validated server-side data from the pinned DatasetVersion.
- [ ] A report can create two useful Global Superstore dashboards without Superset running.
- [ ] AI layout proposals cannot save until preview, quality checks, and explicit approval complete.
- [ ] Every approved mutation creates one restorable DashboardRevision.
- [ ] Existing analysis, report, chart editing, export, and optional Superset publishing remain operational.
