# Delivery Correctness Implementation Plan

> Execute inline with superpowers:executing-plans in the user-selected V2 directory. Preserve the dirty worktree; no commits, downloads or GitHub publication in this task.

**Goal:** Fix scope propagation, ordering, evidence-grounded presentation and local delivery consistency.

**Architecture:** Add small semantic and delivery modules around the current pipeline. Preserve compatibility APIs and immutable originals. Persist completion with the delivery transaction and serialize local enqueue/retry operations; test real process exits using owned children.

**Tech Stack:** Existing FastAPI, SQLAlchemy/SQLite, pandas, DuckDB, pytest, Vue/Playwright; no new dependencies.

**Spec:** Current user request and docs/alpha-acceptance-2026-09-08.md failure cases.

## Global constraints

- Single-machine, no login. No added cloud services or plugin market.
- No relaxing N:1 aggregation protection; daily reconciliation must have a bounded grain.
- Failed/incomplete requirements remain visible, never relabelled as model success.

## 1. Semantic execution

Files: app/capabilities.py, report_requirements.py, new app/analysis_semantics.py, tests/test_delivery_semantics.py.

- [x] Reproduce ordering with `[report.build, sql.query, assistant.synthesize]`; assert SQL precedes deepen and report.
- [x] Run a loss fixture with positive and negative Profit; assert diagnostic scope includes only negative rows and loss magnitudes rank correctly.
- [x] Run Discount grouped fixtures; assert aggregation is mean and no contribution share is emitted.
- [x] Implement `analysis_scope(frame, requirements)` and `aggregation_for(column)`; evidence carries explicit scope/aggregation.
- [x] Re-run focused tests before integrating with execution.

## 2. Focused evidence presentation

Files: new app/result_presentation.py, report_requirements.py, fact_catalog.py, run_execution.py.

- [x] SQL row results must become bounded numeric statements with source aliases, not just row counts; truncated previews explicitly cannot establish full coverage.
- [x] Prefer Region in loss reports and preserve successful SQL blocks in topic reports.
- [x] Add `reconciliation` focus, compare daily groups and unique right values, report coverage boundary/conflicts, omit unrelated seasonal/trend charts.
- [x] Replace unbound summary assertions with selected facts; unsupported model interpretations become explicit rejected claims, never facts.
- [x] Tests reject total-to-daily and marginal-to-joint inferences and check topic block selection.

## 3. Durable delivery and concurrent requests

Files: new app/delivery.py, main.py, run_execution.py, run_runtime.py, schemas.py, tests/test_delivery_faults.py.

- [x] Serialize local enqueue/retry routes; accept explicit planning idempotency key and reject different payload reuse.
- [x] Assign stable report identity per plan across retries, mark incomplete draft, and preserve its identity in Run.
- [x] Commit assistant message, Artifact and completed Run atomically; background wrapper must not complete an already committed Run twice.
- [x] Inject hard exits at report flush, Artifact flush, before commit and after commit; restart and verify partial/completed state and no duplicate delivery.
- [x] Concurrent enqueue/retry tests assert one Run and one Artifact; cancellation notice states retained operations and unknown provider-side billing.

## 4. Backup, migration and acceptance

Files: new scripts/local-backup.py, tests/test_local_backup.py, docs/delivery-correctness-2026-09-08.md.

- [x] Offline backup copies stopped application data into a new destination and records hashes; restore only to a new directory, validates manifest and SQLite integrity, never overwrites user data.
- [x] Roundtrip tests verify data and secret-key bytes retained without printing; compatibility migration tests run twice on legacy schema.
- [x] Run backend regression and frontend build; execute the five real DeepSeek cases once in a separate copy, record tokens and failures.
- [x] Write final evidence and remaining limitations; do not publish to GitHub or restart the user's service.
