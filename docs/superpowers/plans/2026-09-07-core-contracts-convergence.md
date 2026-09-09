# Core Contracts Convergence Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for inline execution. Preserve the user-selected V2 checkout and its existing changes; no worktree relocation or broad commit.

**Goal:** Lock deterministic golden cases, make synthesis evidence-bound, codify domain invariants, and isolate report/run responsibilities without changing existing URLs.

**Architecture:** Keep the current database and compatibility API. Introduce pure synthesis/domain contracts, extract report routes and execution services through explicit dependency ports. Reserve a disabled capability descriptor for future Python plotting; it must grant no execution authority.

**Tech Stack:** Existing FastAPI, SQLAlchemy, Pydantic, pandas, pytest, Vue and Playwright; no added dependencies.

**Spec:** `docs/convergence-plan.md` and the user's four-item scope on 2026-09-07.

## Global Constraints

- Edit only `E:\BI\BI_V2.0`; retain single-machine no-login mode and existing API paths.
- No dependency downloads, original dataset edits, new external permissions or enabled Python plotting.
- Golden tests run offline in isolated test storage/database. Real model runs are a separate, explicitly labelled gate.
- Keep compatibility exports used by current tests while moving implementation out of main.py.

## Task 1 — Golden cases and synthesis contract

Files: create `backend/tests/test_core_golden.py`; modify `backend/app/prompting.py`.

Interfaces: `validate_synthesis(raw, evidence) -> StructuredSynthesis` and `render_synthesis(result) -> str` remain compatible.

- [x] Add fixed retail rows with known sum/profit/ranking and hourly/daily grain fixtures; assert values independently of generated wording.
- [x] Add synthesis cases for existing qualitative output, bound numeric values, incorrect value/reference, duplicate conflicting evidence and unsupported numeric assertions.
- [x] Verify the new valid binding case initially fails against v2.
- [x] Implement v3: numeric placeholders resolve only from named evidence scalar paths, never from model-calculated values. Preserve old qualitative responses. Validate references and render server-owned values; invalid output retains explicit fallback.

Example contract: `{"summary":"总量为 {{total}}。","bindings":[{"name":"total","evidence_id":"total","path":"value"}],"claims":[],"limitations":[]}`. A missing path, unknown evidence ID or literal unbound number fails closed.

Run: `D:\PY\python.exe -m pytest -q tests/test_core_golden.py tests/test_api.py` from backend.

## Task 2 — Domain invariants and extension boundary

Files: create `backend/app/domain.py`, `docs/domain-invariants.md`; extend golden tests.

Interfaces: `transition_run(run, target)` rejects illegal terminal re-entry; `reserved_capabilities()` returns disabled, unavailable descriptors only.

- [x] Test queued→running→completed, terminal re-entry rejection, queued cancellation and failed/interrupted retry as new Run.
- [x] Implement state transition guard and use it in the extracted local runner.
- [x] Document immutable DatasetVersion semantics, version-bound report/Evidence provenance, new Run per retry, distinct ReportVersion/Artifact responsibilities and compatibility gaps.
- [x] Reserve `python.visualize` as unavailable/default-off without registering an executable tool or altering tool policy.

## Task 3 — Report and run implementation boundaries

Files: create `backend/app/report_routes.py`, `backend/app/run_execution.py`, `backend/app/run_runtime.py`; modify `backend/app/main.py`.

Interfaces: report APIRouter preserves existing report CRUD/history/export URLs; execution accepts explicit ports for remaining cleaning/publication integration callbacks; runtime receives session factory, executor and event writer, never imports main.

- [x] Extract report CRUD/history/export routes with explicit imports; leave chart-specific routes unchanged for this bounded iteration.
- [x] Extract `_execute_chat_plan` implementation; main keeps only a compatibility wrapper and dependency composition.
- [x] Extract background execution orchestration and enforce queued-only entry plus domain transitions; preserve event/recovery compatibility wrappers.
- [x] Run API cancellation/recovery/idempotency tests and full backend suite; verify no route duplicate and no reverse import from extracted modules into main.

## Task 4 — Acceptance

- [x] Run full backend pytest, frontend build, browser suite and `git diff --check -- BI_V2.0`.
- [x] Update convergence docs with verified counts, remaining real-model gate and actual extraction scope; do not equate offline golden success with commercial readiness.
- [x] Do not commit unrelated accumulated work.

## Verification result

2026-09-07: backend 93 passed; browser 7 passed; production build passed. Existing pytest cache permissions emit a warning only. Real DeepSeek was not called in this round; v3 live-model reliability remains an explicit separate gate. The extracted main module is approximately 2,282 lines; chart/integration routes and further per-tool decomposition remain outside this bounded pass. No new dependencies or permission grants.
