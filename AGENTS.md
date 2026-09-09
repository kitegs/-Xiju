# Insight Studio V2.0 — agent guide

## Scope and boundaries

- Work only in `E:\BI\BI_V2.0` unless the task explicitly requires otherwise.
- `E:\BI\BI_V1.0` is the legacy reference implementation. Do not edit, delete, stage, or reformat it.
- `E:\BI\frame` contains downloaded third-party source trees for reference only. Do not modify or run their full test suites as part of V2.0 checks.
- Preserve user-created files under `artifacts/` and `开发文档.txt`; they are not application source.
- Do not download/install new dependencies or Docker images without explicit user approval.

## Product intent

Insight Studio is a local-first AI data-analysis and reporting platform for individuals and small teams. It must:

- let beginners analyze uploaded data through a transparent, approval-based AI workflow;
- keep evidence, generated SQL/Python, data-cleaning steps, and report history reviewable;
- provide a direct-manipulation report editor and a chart workbench;
- use Superset for advanced dashboard editing while keeping uploaded originals immutable;
- default to single-machine, no-login usage and add team controls only where required.

Prefer a correct, explainable result over a visually impressive mock implementation. Do not label a chart type as supported if its renderer is only a placeholder.

## Repository map

- `backend/app/` — FastAPI application, analysis tools, persistence, exports, and integrations.
- `backend/tests/` — V2.0 backend regression tests.
- `frontend/src/` — Vue application and editor/workbench UI.
- `deployment/superset/` — local Superset configuration.
- `scripts/run-api.ps1` — local API launcher.
- `scripts/run-web.ps1` — local Vite launcher.
- `scripts/run-superset.ps1` — Docker/Superset launcher.
- `start.bat` — normal local mode.
- `start-professional.bat` — starts/checks Superset, then normal mode.

## Local development and checks

Run V2.0 tests only from the indicated directories:

```powershell
Set-Location E:\BI\BI_V2.0\backend
D:\PY\python.exe -m pytest -q

Set-Location E:\BI\BI_V2.0\frontend
npm.cmd run build
```

Do not run `pytest` from `E:\BI`; it will collect V1 and third-party framework tests.

The API listens on `http://127.0.0.1:8010`. The frontend launcher selects a free Vite port, normally in `5173`–`5190`; never hard-code one frontend port in user-facing integrations.

## Superset integration rules

- Superset is optional in normal local mode and expected only in professional mode.
- Keep original uploaded data immutable. Publishing writes only a curated analysis copy.
- Guest tokens are view-only. Opening the full Superset editor requires the local Superset account; do not describe it as SSO.
- Embedded Superset dashboards require an allow-list matching the actual browser origin before guest-token exchange. Use `normalize_embedded_domains()` / `repair_embedded_dashboard()` in `backend/app/external_bi.py` instead of creating ad-hoc allow-lists.
- External publication, dashboard writes, or configuration repair must remain protected by the existing `report.publish` permission and auditable.

## Security and data handling

- Keep model API keys server-side; never send them to the Vue client or logs.
- Use the existing tool-policy and sandbox paths for generated Python/SQL. Do not grant unrestricted host execution as a convenience shortcut.
- Retain the approval boundary for externally visible writes and destructive actions.
- For non-sensitive local data, the system may use a transparent low-friction workflow, but calculations must still cite their inputs and execution evidence.

## UI and implementation conventions

- Use Chinese UI copy consistent with the existing product.
- Keep chart specifications data-driven and compatible with `ChartPreview.vue`, the report editor, and Superset publishing.
- Provide keyboard/click alternatives whenever drag-and-drop is introduced.
- Use the shared `ContextMenu.vue` for new right-click commands; destructive commands must preserve confirmation.
- Make separate scroll regions explicit for field lists, long panels, and editors; do not rely on page scroll to expose core controls.
- When adding a new real chart type, implement renderer, field compatibility checks, ChartSpec serialization, report-editor behavior, and Superset mapping together.

## Git discipline

- Inspect `git status` before edits. The enclosing `E:\BI` worktree may be dirty for unrelated reasons.
- Stage only files directly related to the requested V2.0 task.
- Do not use `git reset --hard`, broad clean operations, or formatting across V1/frame.
- Before committing, run `git diff --check` and the relevant backend/frontend checks above.
