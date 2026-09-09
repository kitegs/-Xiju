# Evidence-first quality loop implementation plan

## Goal

Close the report delivery loop with structured claims, bounded follow-up computation,
chart/narrative consistency checks, and one reproducible real-provider DOCX acceptance run.

## Tasks

- [x] Add server-owned structured claims and allow semantically equivalent factual rewrites.
- [x] Add bounded, read-only result-driven diagnostics and attach their evidence to reports.
- [x] Cross-check chart data, bindings, units, periods, ranks, and narrative evidence links.
- [x] Add regression tests and run the backend/frontend suites.
- [x] Run a real DeepSeek analysis against the imported Global Superstore dataset.
- [x] Export the new report to DOCX, render every page, inspect it, and record acceptance evidence.

## Acceptance record

- Result: `docs/global-superstore-acceptance-2026-09-06.md`
- DOCX rendering: the canonical LibreOffice renderer was attempted first but LibreOffice was not
  installed. The accepted fallback used hidden Microsoft Word PDF export and bundled Poppler page
  rendering; all seven pages were inspected after the final layout iteration.

## Guardrails

- Never mutate the imported source file.
- Do not expose provider secrets in logs or acceptance output.
- No arbitrary generated SQL or Python in the follow-up analysis loop.
- A real acceptance run creates a new report and artifact; it does not overwrite an existing report.
