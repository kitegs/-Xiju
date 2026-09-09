# Multi-table Release Candidate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the local single-user release-candidate hardening and add safe, evidence-backed `1:1` and `N:1` CSV/Excel analysis using an immutable materialized copy.

**Architecture:** Keep every uploaded source immutable. A new relationship service profiles candidate keys, rejects many-to-many joins, prefixes right-side fields, records grain and non-additive warnings, then materializes an independently versioned dataset for the existing chart/report/AI pipeline. Existing APIs remain compatible because downstream analysis still consumes one Dataset, while lineage carries both source DatasetVersion IDs.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic, pandas, DuckDB, Vue 3, pytest, Vite.

**Spec:** `docs/convergence-plan.md`

## Execution checkpoint — 2026-09-07

Tasks 1–4 and the deterministic/runtime/browser checks in Task 5 are implemented and verified. The original detailed checklist below is retained as the design baseline, not the current status tracker. Current acceptance and limitations are recorded in `docs/bike-sharing-multitable-acceptance.md`.

- [x] Relationship service, compatible APIs, semantic versioning and builder UI.
- [x] Real Bike Sharing source hashes, grain, totals and duplicate-aggregation checks.
- [x] Backend suite (74 passed), browser suite (7 passed), production build.
- [x] DOCX visual review and long-lineage appendix layout repair.
- [ ] Complete-model acceptance: latest real synthesis is explicitly degraded.
- [ ] Production release gates: interpretation quality, relationship submission idempotency/resource limits and cancellation stress tests.

Do not equate deterministic report validation with complete-model or commercial acceptance.

## Global Constraints

- Work only in `E:\BI\BI_V2.0`; source files and V1/framework trees remain read-only.
- Do not add dependencies or require Superset for normal local startup.
- Support only `1:1` and left-`N:1` relationships in this iteration; reject `N:N` and suggest swapping sides for `1:N`.
- Never overwrite source datasets. Applying a relationship creates a new Dataset and DatasetVersion.
- Every relationship preview and materialized output must expose row counts, match rates, duplicate-key risks, field lineage, and non-additive right-side measures.
- Keep existing single-dataset API and UI paths working.

---

### Task 1: Relationship profiling and safe materialization service

**Files:**
- Create: `backend/app/relationships.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_relationships.py`

**Interfaces:**
- Consumes: `read_dataframe(storage_key)`, `profile_dataframe(frame)`.
- Produces: `profile_relationship(left, right, left_keys, right_keys, join_type) -> RelationshipProfile`; `materialize_relationship(...) -> tuple[pd.DataFrame, RelationshipProfile, dict]`.

- [ ] Write tests using one unique daily table and one repeated hourly table.
- [ ] Verify `hour.day_id -> day.day_id` is classified `many_to_one`, with exact match and output counts.
- [ ] Verify reversed `day -> hour` is rejected with a swap-side message.
- [ ] Verify duplicated keys on both sides are rejected as many-to-many before merge.
- [ ] Implement key validation, null/duplicate statistics, matched/unmatched counts and output-row estimate.
- [ ] Prefix all non-key right fields and mark right numeric fields non-additive after `N:1` expansion.
- [ ] Materialize with pandas `merge(validate="many_to_one"|"one_to_one")` and preserve a compact field-lineage map.
- [ ] Run `D:\PY\python.exe -m pytest -q tests/test_relationships.py`.

### Task 2: Durable relationship model and compatible APIs

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/database.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_relationships.py`

**Interfaces:**
- Produces: `POST /api/v1/dataset-relationships/preview`, `POST /api/v1/dataset-relationships`, `GET /api/v1/dataset-relationships`.

- [ ] Add `DatasetRelationship` with source IDs/version IDs, keys, join type, cardinality, profile, result dataset ID and timestamps.
- [ ] Add request/response schemas with maximum four key columns and `left|inner` join types.
- [ ] Preview without writes and reject cross-workspace datasets.
- [ ] Apply into a new UTF-8 CSV Dataset, create its DatasetVersion, and persist lineage to both the relationship and result profile.
- [ ] Delete a partially written target if the transaction fails.
- [ ] Assert originals retain identical SHA-256 hashes and the result DatasetVersion includes both source version IDs in lineage metadata.
- [ ] Run relationship API tests.

### Task 3: Dataset semantics, date/unit metadata and AI aggregation guard

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/database.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/services.py`
- Modify: `backend/app/prompting.py`
- Test: `backend/tests/test_relationships.py`
- Test: `backend/tests/test_services.py`

**Interfaces:**
- Produces: `PATCH /api/v1/datasets/{dataset_id}/semantics`; Dataset output field `semantics`.

- [ ] Add server-owned semantics for column roles, units/currency, date formats, grain, lineage and non-additive columns.
- [ ] Validate semantic column names against the real dataframe and keep originals unchanged.
- [ ] Let explicit date formats flow through `convert_type` and report trend parsing.
- [ ] Add common bike aliases (`dteday`, `cnt`, `registered`, `casual`) and low-cardinality dimensions without treating ID fields as measures.
- [ ] Include relationship grain and non-additive warnings in AI planning/synthesis context.
- [ ] Reject formal sums of fields marked non-additive in generated SQL and deterministic report selection.
- [ ] Test date recognition and the daily-total duplication guard.

### Task 4: Relationship builder in the data workspace

**Files:**
- Create: `frontend/src/components/RelationshipBuilder.vue`
- Modify: `frontend/src/components/DataWorkbench.vue`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/style.css`

**Interfaces:**
- Consumes: relationship preview/apply/list APIs.
- Produces: `dataset-created` with the materialized Dataset, allowing immediate AI analysis.

- [ ] Add a “多表关联” data tab without changing existing preview/cleaning/history tabs.
- [ ] Let users choose the left detail table, right lookup/summary table, keys and left/inner join.
- [ ] Preview cardinality, match rate, unmatched rows, output rows, collision prefix and non-additive warnings.
- [ ] Disable apply for `N:N`, reversed `1:N`, missing keys or zero matches.
- [ ] Require explicit confirmation that right-side numeric fields may not be summed after expansion.
- [ ] Apply, add the new dataset to App state, select it, and expose “交给 AI 分析”.
- [ ] Add responsive layout and keyboard/click operation; do not depend on drag-and-drop.
- [ ] Run `npm.cmd run build`.

### Task 5: Runtime/recovery regression and Bike Sharing acceptance

**Files:**
- Create: `scripts/accept-bike-multitable.py`
- Create: `docs/bike-sharing-multitable-acceptance.md`
- Modify: `docs/convergence-plan.md`
- Modify: `docs/requirements-vnext.md`
- Modify: `docs/target-architecture-commercial.md`
- Test: `backend/tests/test_relationships.py`

**Interfaces:**
- Consumes: the relationship APIs and existing report generation API.
- Produces: reproducible JSON acceptance output under `data/acceptance/<timestamp>/`.

- [ ] Verify queued-run recovery, interrupted-run marking, idempotent retry and SSE terminal events remain covered by tests.
- [ ] Import the real `day.csv` and `hour.csv` through the upload API into copies.
- [ ] Preview and apply `hour.dteday -> day.dteday`; assert 17,379 output rows, 731 matched dates, no unmatched hour rows and no source hash changes.
- [ ] Verify `cnt` equals `casual + registered` on both grains and record independent source totals.
- [ ] Generate a report from the materialized dataset and assert its evidence does not sum prefixed daily totals.
- [ ] Record source hashes, relationship profile, result hash, report quality and known interpretation limits without API keys.
- [ ] Run the full backend suite, frontend build, script acceptance, and `git diff --check -- BI_V2.0`.

## Completion gate

- Single-dataset upload/cleaning/report flows still pass.
- Multi-table preview blocks unsafe joins before materialization.
- Bike Sharing `hour -> day` acceptance is repeatable and leaves both source files unchanged.
- AI/report context states the joined grain and non-additive right-side fields.
- Backend tests, frontend production build and diff checks pass.
