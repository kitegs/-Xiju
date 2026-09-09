# Report Contract Pipeline Implementation Plan

> **For agentic workers:** Execute inline in the user-selected V2 checkout with review checkpoints; no subagents, downloads or commits without user request.

**Goal:** Make report requirements executable while retaining verified computation and approved edits.

**Architecture:** A ReportRequirements value travels in AnalysisOptions and saved Run snapshots. A named fact catalog renders factual claims server-side. A report composition module selects evidence and sections after fixed calculations. Planning becomes a persistent cancellable Run without auto-executing tools in the worker.

**Tech Stack:** Existing FastAPI/Pydantic, SQLite Run queue, pandas, Vue, pytest/Playwright, DOCX export.

**Spec:** User-approved five steps from 2026-09-08; AGENTS.md; docs/convergence-plan.md.

**Checkpoint:** First bounded implementation and offline/browser/export acceptance completed. See `docs/report-contract-acceptance-2026-09-08.md` for exact coverage and open gates. This is not a claim that arbitrary free-text requirements or live model stability are solved.

## Global Constraints

Single-machine no-login; original files unchanged; tool policy and save approvals unchanged. No extra plotting libraries, cloud deployment or enterprise accounts. Legacy API and saved v3 summaries remain readable. Supported report presets are bounded and unsupported free-text requirements must be shown for review, not claimed fulfilled.

## Task 1: Fact and tool contracts

Files: new `backend/app/fact_catalog.py`; prompting.py, capabilities.py, run_execution.py; new tests/test_report_requirements.py.

- [ ] Test `validate_fact_summary({'facts':['missing']}, evidence)` rejects; ensure factual text is generated from a catalog entry, never model-relabelled operands.
- [ ] Implement v4 fact catalog with stable IDs, roles, units and formatted text; live synthesis uses v4, legacy validator stays for stored responses. Reject unknown facts and unbound numerical prose; expose rejected claim counts.
- [ ] Pass `DiagnosticChoice.model_json_schema()` and named candidate lists; arrays remain invalid. Stop redundant same-content field analysis without reporting it as successful new work.

## Task 2: Executable report requirements

Files: new report_requirements.py and ReportRequirements.vue; schemas.py, main.py, services.py, run_execution.py, App.vue.

- [ ] Resolve explicit UI fields before inferred defaults: depth brief/standard/detailed, focus general/loss/hourly, audience, exclusions and requested requirements.
- [ ] Test same frame totals remain equal while brief/ detailed blocks differ and loss-only excludes general sales ranking.
- [ ] Carry requirements through planning, saved AnalysisOptions and report metadata. Show unresolved requirements as not yet verified.

## Task 3: Result-driven composition

Files: report_requirements.py, capabilities.py, run_execution.py.

- [ ] Attach selected SQL/deep evidence to report; deduplicate method and underlying field content; preserve all audit evidence.
- [ ] Select substantive findings before rendering rather than changing only summary text. For loss focus compute grouped loss amount/count using fixed code and mark causal explanations unverified.
- [ ] Generate conditional next actions: invalid dates require repair before growth analysis, hourly demand retains observation denominators.

## Task 4: Durable planning and export

Files: new planning_runtime.py; main.py, run_runtime.py, App.vue, exporting.py.

- [ ] Add `/chat/plan-async`, placeholder message and Run kind=planning request snapshot. Queue worker invokes existing planning logic in isolated session, stores result message; cancellation and restart use Run lifecycle.
- [ ] Client awaits planning Run terminal state, permits stop, never auto-executes cancelled planning. Preserve `/chat/plan` compatibility.
- [ ] Respect brief appendix visibility; distinguish calculation check from human review; remove forced action page break. Render representative DOCX with local Word if LibreOffice unavailable.

## Task 5: Acceptance

- [ ] Offline same-input contrasting requirements tests; invalid facts/tool args; planning run lifecycle and no execution after cancellation.
- [ ] Run isolated backend suite, frontend build and browser tests. Inspect rendered outputs separately from numerical checks. Record exact results and remaining limits in docs.
- [ ] Real provider tests are a separate budgeted gate; no mock result counts as model stability evidence.
