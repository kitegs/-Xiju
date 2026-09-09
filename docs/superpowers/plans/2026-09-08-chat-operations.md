# Chat Operations Implementation Plan

> **For agentic workers:** Execute inline in the user-selected V2 checkout; preserve existing changes. No delegation or dependency installation.

**Goal:** Expose actual execution in chat, add stop controls and recoverable bulk management.

**Architecture:** Reuse persistent Run events and existing report deletion APIs. Separate an execution-details component from App.vue. Archive conversations rather than erase messages and run provenance.

**Tech Stack:** Vue, FastAPI, pytest, existing Playwright.

**Spec:** User request of 2026-09-08; AGENTS.md; docs/convergence-plan.md.

## Global Constraints

Single-machine no-login; unchanged tool permissions; no paid model tests or dependency downloads. Batch selection means report/conversation list entries, not individual report blocks or messages. Selection is scoped to visible page. Show partial failures. Keep generated secrets out of UI; show only existing execution evidence, not hidden model reasoning.

## Tasks

- [ ] Persist step result metadata and evidence in Run events: `data={"execution": tool_runs[-1], "evidence": matching_evidence}`. Display status, input/output, code, evidence in `ExecutionDetails.vue`; use GET run events when opened and refresh while active. Legacy completed messages remain supported.
- [ ] Add composer stop: abort pending planning fetch and guard automatic execution; invoke existing run cancellation for active runs. State explicitly that aborted planning may still consume provider tokens. Refresh cancelled plan status.
- [ ] Use Conversation.archived for delete; add archived listing and restore, reject deletion of queued/running conversation. Add report and conversation checkbox controls with visible-page select, confirmation and sequential existing endpoint calls; retain failed selections.
- [ ] Backend test archived messages survive, restore and running guard. Frontend build plus existing isolated E2E; verify no real user data is deleted by tests.

## Checks

Implementation checkpoint: execution details, planning abort/run cancel entry, conversation archive/restore and bulk list controls implemented. Frontend 10 E2E passed (three new cases); backend final verification recorded in the handoff. Planning cancellation is explicitly best-effort client abort, not upstream hard cancellation. Report personalization is assessed but not changed in this scope. No user records were deleted.

`D:\PY\python.exe -m pytest -q` from backend; `npm.cmd run build` and `npm.cmd run test:e2e` from frontend. Do not commit unrelated dirty work. Document that report personalization remains an independent unresolved gate.
