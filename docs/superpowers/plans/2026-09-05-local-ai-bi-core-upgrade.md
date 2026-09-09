# Local AI BI Core Upgrade Master Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Coordinate the four approved upgrade tracks into releasable increments while preserving the current no-login single-machine product after every increment.

**Architecture:** Execute four focused plans in dependency order. Each plan owns its schemas, services, APIs, UI and tests; shared model/schema edits are integrated at phase boundaries and verified against the full regression suite.

**Tech Stack:** FastAPI, SQLAlchemy async, SQLite, Pandas/DuckDB, Vue 3, ECharts, pytest, Playwright, python-docx.

**Spec:** `docs/superpowers/specs/2026-09-05-local-ai-bi-core-upgrade-design.md`.

## Global Constraints

- Work on the existing branch and preserve unrelated working-tree changes.
- Stage and commit only files belonging to the completed phase.
- Use test-first implementation within every task.
- Keep compatibility APIs, single-machine startup, manual chart/report editing and DOCX export working throughout.
- Do not start user management, authentication, Redis/Celery, plugin marketplace work, or mandatory Superset integration.

---

## Phase 1: Trust and requirements intake

**Plan:** `docs/superpowers/plans/2026-09-05-token-and-analysis-intake.md`

- [ ] Complete stage-aware Token logging and Token Center APIs/UI.
- [ ] Complete AnalysisBrief, the repository-owned intake skill, and the composer clarification menu.
- [ ] Verify default assumptions appear in report metadata and visible report content.
- [ ] Pass backend regression, frontend build and clarification/Token Playwright flow.
- [ ] Commit this phase independently.

**Release checkpoint:** Users can see actual provider Token usage, and report/dashboard requests no longer proceed on hidden business assumptions.

## Phase 2: Reliable time and commercial output

**Plan:** `docs/superpowers/plans/2026-09-05-date-recovery-and-commercial-report.md`

- [ ] Complete date diagnostics and new-version `Order Year` recovery.
- [ ] Expand deterministic Global Superstore calculations and evidence-bound report sections.
- [ ] Verify totals against independent DuckDB SQL.
- [ ] Generate, render and visually inspect the DOCX artifact.
- [ ] Pass backend regression, frontend build and golden-flow Playwright test.
- [ ] Commit this phase independently.

**Release checkpoint:** The included sample produces a credible, explanatory commercial report without fabricated dates or unsupported numbers.

## Phase 3: AI changes to the whole report

**Plan:** `docs/superpowers/plans/2026-09-05-whole-report-ai-patchset.md`

- [ ] Complete typed ReportPatchSet schemas and persistent proposals.
- [ ] Complete server-side preview, deterministic chart recomputation, quality comparison, approval and rollback.
- [ ] Route natural-language whole-report requests into the proposal experience.
- [ ] Pass stale-version, invalid-reference, rollback and end-to-end report edit tests.
- [ ] Commit this phase independently.

**Release checkpoint:** AI can improve a complete report, but no AI request can overwrite it without a visible diff and explicit approval.

## Phase 4: Multiple local dashboards per project

**Plan:** `docs/superpowers/plans/2026-09-05-local-dashboard-module.md`

- [ ] Complete DashboardDocument, Dashboard and DashboardRevision persistence.
- [ ] Complete dashboard CRUD, filters, interactions, view/edit/fullscreen modes and revision restore.
- [ ] Complete report-to-dashboard conversion and typed AI layout proposals.
- [ ] Create and verify `经营总览` and `利润与折扣风险` under the Global Superstore Project.
- [ ] Prove the full local dashboard workflow works while Superset is stopped.
- [ ] Pass all backend, build and Playwright checks.
- [ ] Commit this phase independently.

**Release checkpoint:** A Project supports multiple useful dashboards locally, with Superset remaining an optional publish destination.

## Final Release Gate

- [ ] Run `python -m pytest backend/tests -q` from `E:\BI\BI_V2.0`.
- [ ] Run `npm run build` and `npm run test:e2e` from `E:\BI\BI_V2.0\frontend`.
- [ ] Run the complete Global Superstore verification script and archive its IDs, hashes and assertions.
- [ ] Regenerate and visually inspect the DOCX report after the final schema/UI changes.
- [ ] Confirm no login is required and `start.bat` reaches a healthy API and frontend.
- [ ] Confirm Token Center contains no currency display and no fabricated token estimates.
- [ ] Confirm one Project contains at least two independently editable dashboards.
- [ ] Confirm every report claim and chart links to existing Evidence.
- [ ] Run `git diff --check` and review the complete release diff for accidental source-data or secret changes.
