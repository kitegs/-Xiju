# Alpha Acceptance Implementation Plan

> Execute inline in the explicitly selected V2 directory using executing-plans checkpoints. Preserve the dirty worktree. No downloads, commits, external publication, or third-party plugin loading.

**Goal:** Validate five real DeepSeek scenarios, fault recovery, fresh-data onboarding, and one built-in extension.

**Architecture:** Run current API code against a separate local acceptance database. Snapshot source files and copy only selected dataset files, encrypted provider settings and local key inside ignored acceptance storage. Record all five first attempts including degraded results. Fault injection uses isolated offline tests, never disconnects the user's network or kills their service. A built-in registry delegates report.layout while the normal tool-policy and report-save pipeline remain authoritative.

**Tech Stack:** Existing FastAPI, SQLite, httpx, pytest, Vue and Playwright. No new dependencies.

**Spec:** User request in this task: real contrasts, interruption/network/process/retry faults, clean first use, minimum extension interface.

## Task 1 Real contrasts

Files: scripts/accept-alpha.py, existing app configuration and five saved acceptance folders.

- [x] Implement `prepare(destination)` using SQLite backup into a new ignored directory, copy selected dataset storage keys and encryption key, disable queued historical runs in the copy. Assert source hashes unchanged after execution.
- [x] Start an owned API process on a free loopback port using `AIBI_DATA_DIR`. Do not use/restart the user's API.
- [x] Execute brief/loss/detailed Superstore and hourly/reconciliation Bike once each via asynchronous planning and execution. Record `synthesis_validation`, errors, tool paths, document sections and usage by stage. Never mark a fallback as a model pass.
- [x] Compare saved reports and narrative against task-specific criteria; preserve failed runs rather than retry until green. All totals independently match; semantic acceptance is NOT universally passed.

## Task 2 Fault regression

Files: backend/tests/test_runtime_faults.py; main.py and run_runtime.py only if regression proves a defect.

- [x] Assert cancelling a running planner and running executor leads to cancelled, not completed; no automatic artifacts.
- [x] Inject `httpx.ConnectError` at the model boundary; assert explicit degraded status rather than false model success.
- [x] Use isolated restart recovery for queued/running state and verify records persist, including a killed owned process.
- [x] Repeat retry requests against one cancelled planning Run; assert identical returned Run id and no duplicate placeholder. Enforce DB unique idempotency key with collision handling. Also verify repeated execution retry creates one report Artifact.

## Task 3 First-use acceptance

Files: frontend/e2e/first-use.spec.js; docs/quick-start-local.md; scripts/check-local-readiness.ps1.

- [x] Test bootstrap without login, provider settings with a dummy key (no network), example import, report generation, editing and saving under isolated test storage.
- [x] Check installed runtimes/dependency readiness without installation. Clean application data tested; clean OS and real unfamiliar human unverified.
- [x] Document first-run steps and where to find failures, evidence, token counts and limitations.

## Task 4 Minimum extension

Files: backend/app/extensions.py, run_execution.py, main.py, backend/tests/test_extensions.py.

- [x] Test `execute_builtin('report.layout', document, enabled=False)` rejects without mutation; unknown tools reject. Failed handlers also leave the draft unchanged.
- [x] Register the existing layout function with id/version/core-contract metadata and an explicit enable flag. Invoke through the registry inside the existing policy-controlled executor; persist plugin version in component results.
- [x] Expose read-only manifest information. No dynamic imports, installation or arbitrary plugins.

## Final gates

- [x] Run isolated backend tests and frontend build/browser tests; write docs/alpha-acceptance-2026-09-08.md with exact evidence and unresolved limits. Final: backend 114 passed; browser 11 passed; production build passed. Live suite: 60,624 tokens, semantic failures retained.
- [x] Check changed source for whitespace and secrets. Never print API keys or put them in acceptance JSON/Markdown. Sensitive copied runtime is git-ignored; do not publish it.
