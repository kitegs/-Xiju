# Date Recovery and Commercial Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Diagnose irrecoverable date damage honestly, create a reliable `Order Year` dataset version, and expand the Global Superstore report into an evidence-backed commercial deliverable.

**Architecture:** Date recovery is a typed cleaning operation that always writes a new DatasetVersion and never mutates the imported file. The deterministic report builder selects useful sections from available fields, computes all values from the complete dataframe, and binds every displayed claim to Evidence before optional model-written narrative.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy, Pandas, DuckDB, python-docx, Vue 3, ECharts, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-05-local-ai-bi-core-upgrade-design.md` sections 4.3, 4.4, 5.2, 7 and 8.2.

## Global Constraints

- Treat `Order Date` and `Ship Date` values equal to `00:00.0` as destroyed information, not parseable dates.
- Default recovery creates `Order Year` from the reliable `Year` field with `precision=year`.
- `Year + weeknum` is an explicit approximate option only; never use it for default forecasting or label it as an exact order date.
- Do not recover `Ship Date` when no reliable source field exists.
- Never overwrite a source file or current DatasetVersion. Preview first, then create a new version plus CleaningRecipe.
- Report numbers and chart data must come from the full dataframe. Model text may summarize Evidence but may not invent metrics.
- Use no more than nine non-KPI views in the report body; extra useful views belong in Dashboard.

---

## Task 1: Add a typed date-recovery diagnostic contract

**Files:**
- Modify: `backend/app/schemas.py`
- Create: `backend/app/date_recovery.py`
- Test: `backend/tests/test_services.py`

- [ ] Add failing tests for destroyed time-only strings, reliable numeric/string years, invalid years, approximate year-week availability, and absent recovery sources.
- [ ] Define `DateFieldDiagnosis`, `DateRecoveryCandidate`, `DateRecoveryPreviewRequest`, `DateRecoveryPreviewOut`, and `DateRecoveryApplyRequest`.
- [ ] Implement `diagnose_date_recovery(frame)` without model calls.
- [ ] Mark each candidate with `target_column`, `source_columns`, `precision`, `reliable`, `approximate`, `coverage`, `warning`, and a preview of distinct values.
- [ ] Reject years outside 1900–2100 and ISO week values outside 1–53.
- [ ] Detect collisions when `Order Year` or `Approx Order Period` already exists and require an explicit new target name.
- [ ] Run `python -m pytest backend/tests/test_services.py -k "date_recovery" -q`.

Core result for Global Superstore:

```json
{
  "target_column": "Order Year",
  "source_columns": ["Year"],
  "precision": "year",
  "reliable": true,
  "approximate": false,
  "coverage": 1.0,
  "warning": "原 Order Date 已损坏；仅恢复年份，不代表精确订单日期"
}
```

## Task 2: Add `derive_period` to the cleaning engine

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/services.py`
- Test: `backend/tests/test_services.py`

- [ ] Extend `CleaningStep.operation` with `derive_period` and add `new_name`, `secondary_column`, and `precision: year|year_week` fields.
- [ ] Add validation: `year` accepts one source column; `year_week` requires the secondary week column and explicit `allow_approximate=true`.
- [ ] Implement year output as nullable integer and year-week output as the sortable string `YYYY-Www`.
- [ ] Include precision and source columns in the cleaning step result description.
- [ ] Verify malformed values become null and are counted in `changed_cells` without changing row count.
- [ ] Run `python -m pytest backend/tests/test_services.py -k "derive_period" -q`.

Use this request shape:

```json
{
  "operation": "derive_period",
  "column": "Year",
  "new_name": "Order Year",
  "precision": "year",
  "allow_approximate": false
}
```

## Task 3: Expose preview/apply APIs and preserve lineage

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_api.py`

- [ ] Add failing API tests that record the original storage file SHA-256, preview recovery, apply it, and assert the original hash is unchanged.
- [ ] Add `POST /api/v1/datasets/{dataset_id}/date-recovery/preview`; load the current DatasetVersion and return diagnostics plus a 20-row preview.
- [ ] Add `POST /api/v1/datasets/{dataset_id}/date-recovery/apply`; require one candidate copied exactly from a fresh preview.
- [ ] Reuse the existing cleaning apply/versioning path rather than duplicating file persistence logic.
- [ ] Persist a CleaningRecipe whose operation is `derive_period`, `source_version_id` is the old version, and `result_version_id` is the new version.
- [ ] Write recovery metadata into the new DatasetVersion profile: `derived_time_fields`, `date_limitations`, and transformation version.
- [ ] Return HTTP 409 if the source version changed between preview and apply.
- [ ] Run `python -m pytest backend/tests/test_api.py -k "date_recovery" -q`.

## Task 4: Add the data-workbench recovery card

**Files:**
- Create: `frontend/src/api/dateRecovery.js`
- Modify: `frontend/src/components/DataWorkbench.vue`
- Modify: `frontend/src/style.css`

- [ ] Add a `日期诊断` card that appears when invalid date fields or reliable replacement sources exist.
- [ ] Show destroyed fields, recoverable precision, coverage, source fields, and warnings in plain Chinese.
- [ ] Default-select only reliable year recovery; put approximate year-week behind an unchecked `允许近似周期` control.
- [ ] Show before/after columns and sample values before enabling `生成新版本`.
- [ ] After apply, refresh the dataset/version once and select the new DatasetVersion without entering a polling loop.
- [ ] Verify the original source is labeled `保持不变` and the derived column is labeled `年份精度`.
- [ ] Run `npm run build` from `frontend`.

## Task 5: Extract reusable deterministic report calculations

**Files:**
- Create: `backend/app/commercial_report.py`
- Modify: `backend/app/services.py`
- Test: `backend/tests/test_services.py`

- [ ] Add tests for KPI totals, yearly sales/profit/margin, top/bottom sorting, negative-profit detail, and field-absence degradation.
- [ ] Implement pure calculation helpers returning rows plus Evidence metadata; do not call the model or database inside them.
- [ ] Keep `services.build_report(...)` as the public compatibility entry and delegate commercial section calculation to the new module.
- [ ] Resolve time in this order: valid date column, reliable derived `Order Year`, then no time section.
- [ ] Add source field names, aggregation, sort, truncation, precision, and unit to every returned evidence record.
- [ ] Use stable chart/evidence IDs so repeated generation from the same DatasetVersion is structurally identical.
- [ ] Run `python -m pytest backend/tests/test_services.py -k "commercial_report or build_report" -q`.

The section selector must evaluate these candidates in order and skip unavailable ones:

```python
SECTION_IDS = (
    "annual_sales",
    "annual_margin",
    "market_contribution",
    "region_profitability",
    "category_structure",
    "segment_performance",
    "ship_mode_cost",
    "discount_profit_risk",
    "product_top_bottom",
    "loss_detail",
)
```

## Task 6: Expand the Global Superstore report document

**Files:**
- Modify: `backend/app/commercial_report.py`
- Modify: `backend/app/services.py`
- Modify: `backend/app/commercial.py`
- Test: `backend/tests/test_api.py`

- [ ] Extend the golden-flow test to assert 4 KPI charts and at least 6 non-KPI charts for Global Superstore.
- [ ] Add yearly sales and yearly profit-margin trend using `Order Year`; state `年份精度` in description and Evidence.
- [ ] Add Market contribution, Region profitability, Category/Sub-Category structure, Segment performance, Ship Mode/shipping cost, discount-profit risk, product top/bottom, and loss-detail candidates.
- [ ] Select six to nine candidates by decision value and field coverage; do not add blank or single-value charts.
- [ ] Use a small multiple or separate margin view when sales and profit scales differ by more than 10×; do not default to dual axis.
- [ ] Add one finding paragraph and one actionable recommendation for each included analytical section, all linked to evidence IDs.
- [ ] Add a limitations block naming destroyed date fields and every defaulted business assumption.
- [ ] Re-run quality assessment and require no error-level issue before export.
- [ ] Run `python -m pytest backend/tests/test_api.py -k "global_superstore or commercial_report" -q`.

Each chart must satisfy:

```python
assert chart.title
assert chart.description
assert chart.evidence_ids
assert chart.style.source_label
assert all(evidence_id in evidence_index for evidence_id in chart.evidence_ids)
```

## Task 7: Improve ECharts rendering for the new report sections

**Files:**
- Modify: `frontend/src/lib/chartOptions.js`
- Modify: `frontend/src/components/ChartPreview.vue`
- Modify: `frontend/src/plugins/echarts.js`
- Test: `frontend/scripts/run-e2e.mjs`

- [ ] Add rendering coverage for grouped/stacked bar, scatter with reference line, top/bottom diverging bar, and evidence-backed detail table.
- [ ] Sort time axes numerically/chronologically and category axes according to the server-provided order.
- [ ] Use the accessible palette, minimum 4.5:1 text contrast, visible units, and a source footer.
- [ ] Show truncation such as `Top 10` in the title/subtitle and show error bars when the chart schema requests them.
- [ ] Import only used ECharts charts/components/renderers in `plugins/echarts.js`; keep the existing lazy component boundary.
- [ ] Run `npm run build` and record the main chunk size in the verification notes.

## Task 8: Generate and visually verify the commercial artifact

**Files:**
- Modify: `backend/app/exporting.py`
- Modify: `scripts/verify-commercial-report.py`
- Modify: `README.md`

- [ ] Extend the verification script to import the canonical Global Superstore source, apply year recovery, generate the report, and compare KPI/year aggregates against independent DuckDB SQL.
- [ ] Export DOCX with section narratives, chart captions, units, source lines, limitations, and unconfirmed assumptions.
- [ ] Render the DOCX to page images using the repository's document verification workflow and inspect every page for clipping, empty pages, unreadable labels, and orphan headings.
- [ ] Save the verification report with dataset hash, DatasetVersion ID, Report ID, chart count, evidence count, quality score, and aggregate assertions.
- [ ] Run `python -m pytest backend/tests -q`.
- [ ] Run `npm run build` and `npm run test:e2e` from `frontend`.
- [ ] Run `git diff --check` and verify no source CSV or imported DatasetVersion was modified in place.

## Acceptance Gate

- [ ] The original Global Superstore file hash is unchanged.
- [ ] `Order Year` is derived in a new DatasetVersion and clearly marked as year precision.
- [ ] No exact order/ship date is fabricated and no approximate week is used by default.
- [ ] Global Superstore retains 51,290 rows and its golden KPI totals.
- [ ] The report contains four KPIs, six to nine meaningful analysis views, explanatory text, limitations, and actionable findings.
- [ ] Every displayed number is bound to deterministic Evidence and independent SQL checks pass.
- [ ] The generated DOCX has been rendered and visually inspected before release.
