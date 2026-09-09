"""Exercise the application's existing exporter with a hand-verifiable fixture.

No model requests, uploaded data mutations, or application database writes.
Run with the application's runtime, then render outputs for visual acceptance.
"""
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services import build_report, profile_dataframe, assess_report_quality
from app.report_requirements import compose_report, resolve_requirements
from app.report_claims import seal_claims
from app.exporting import build_docx

output = Path(__file__).resolve().parents[1] / 'data/acceptance/20260908-requirements'
output.mkdir(parents=True, exist_ok=True)
frame = pd.DataFrame({'Sales': [100, 200, 300], 'Profit': [-10, 40, -20],
                      'Region': ['East', 'West', 'East'],
                      'Order Date': ['2025-01-01', '2025-02-01', '2025-03-01']})
for name, prompt in [('brief', '老板简报'), ('detailed', '详细分析'), ('loss', '只分析亏损，不要趋势')]:
    report = build_report(frame, profile_dataframe(frame), 'Golden', prompt)
    compose_report(report, frame, resolve_requirements(prompt))
    seal_claims(report)
    report.quality = assess_report_quality(report)
    if not report.quality.passed:
        raise ValueError(report.quality.model_dump())
    (output / f'{name}.json').write_text(report.model_dump_json(indent=2), encoding='utf-8')
    (output / f'{name}.docx').write_bytes(build_docx(report.title, report.model_dump(mode='json')))
    print(name, len(report.blocks), len(report.charts), report.quality.score)
