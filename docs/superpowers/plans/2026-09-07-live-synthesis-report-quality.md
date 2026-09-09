# Live Synthesis and Report Quality Implementation Plan

> **For agentic workers:** Execute inline with review checkpoints in the user-selected V2 checkout. Preserve all pre-existing changes.

**Goal:** Run three paid DeepSeek reports per dataset and improve evidence-based explanations without adding tools or permissions.

**Architecture:** A serial acceptance runner talks to one local API, uses current imported data read-only, saves every attempt and stage usage, and separates model success from deterministic report checks. Fixed descriptive calculations supply normalized comparisons; narrative clearly distinguishes observation, interpretation, action and limits.

**Tech Stack:** Existing FastAPI, httpx, pandas, pytest, DOCX exporter and bundled rendering utilities.

**Spec:** `docs/convergence-plan.md`, `docs/domain-invariants.md` and the user's approved next-step sequence.

## Execution checkpoint

Implemented runner, saved diagnostic and synthesis replay, observational calculations, fail-closed synthesis diagnostics and focused tests. Six frozen live attempts completed: one passed automatic pipeline checks, five degraded. Independent totals and source hashes match across repeats. Backend 97 passed, frontend build and diff check passed. Two first-attempt DOCX exports (9 + 13 pages) were visually inspected in full using Word/PDFium because LibreOffice is unavailable.

**Not fully achieved:** stable synthesis, semantic role validation for fact bindings, fully contextual financial recommendations, and commercial document layout. Do not mark these accepted merely because deterministic quality checks pass. Results and next bounded fixes: `docs/live-six-acceptance-2026-09-07.md`. Remaining unchecked quality items below reflect unresolved acceptance, not missing test execution.

## Global constraints

- Single-machine no-login. V2 only. No new dependencies, network tools, Python privileges or original-file mutations.
- DeepSeek only; six primary runs, serial, no silent paid retries. Save degraded/failed runs as failures, not successes.
- Use independent source totals and hashes; do not invent unavailable Superstore dates or currency.
- DOCX inspection is a separate visual/content gate; report provider or quality score alone cannot certify delivery.

## Task 1 — Reproducible live runner

Files: `scripts/accept-live-suite.py`, existing acceptance script compatibility entry points as needed.

- [x] Inspect active API and provider availability without exposing keys; start latest code only when no conflicting service owns the test port/database.
- [x] Create serial runner with `--dataset`, `--repetitions`, `--output`; retain report JSON, assistant response, per-call tokens/latency, source hashes and failure reasons.
- [x] Assert independent totals: Superstore sales 12,642,905, profit 1,467,457.29128 (verify actual file precision first); Bike cnt 3,292,679 and 17,379 hourly rows.
- [x] Run one diagnostic attempt before changes, preserve it separately from final acceptance.

## Task 2 — Evidence-based interpretation

Files: `backend/app/capabilities.py`, `backend/app/services.py`, `backend/app/prompting.py`, `backend/tests/test_capabilities.py` and focused new tests as needed.

- [x] Reproduce failures using saved responses or small fixed data before applying fixes.
- [x] For validated hourly data compute sum, valid observations, observed days, mean per observed hour and mean per observed day by requested category. Missing hours must not become zeros or be labelled complete calendar coverage.
- [ ] Distinguish ranking by total from ranking by normalized demand; include sample-size and observational limits. Remove retail profit advice from non-financial reports.
- [ ] Preserve existing synthesis fail-closed checks; fix protocol/context defects found by live responses without accepting invented numeric values.

Example test: group A has two hourly records 10 and 10, group B one record 15. Total ranks A above B; observed-hour mean ranks B above A. These facts must not be conflated.

## Task 3 — Final acceptance and delivery

- [x] Run three final attempts per dataset on a frozen code version; record all model/component failures, not only provider labels.
- [x] Compare invariant totals across repeats, inspect each report narrative, and export representative final DOCX reports.
- [x] Render and inspect every page of delivered DOCX; no blind export delivery. These are diagnostic samples, not approved commercial drafts.
- [x] Run backend tests, frontend build and diff check. Update convergence/acceptance documents with exact counts, tokens, defects and unresolved gates.
