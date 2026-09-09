"""Export first attempt per case without cherry-picking a successful retry."""
import json
from pathlib import Path
import httpx

root = Path(__file__).resolve().parents[1] / 'data/acceptance/20260907-final-six'
for case in ('superstore', 'bike'):
    folder = root / f'{case}-1'
    report = json.loads((folder / 'report.json').read_text(encoding='utf-8'))
    response = httpx.get(f"http://127.0.0.1:8010/api/v1/reports/{report['id']}/export.docx", timeout=180)
    response.raise_for_status()
    output = folder / f'{case}-report.docx'
    output.write_bytes(response.content)
    print(output)
