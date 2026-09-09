"""Read-only, independent CSV arithmetic; append adjudication, never rewrite attempts."""
import csv
import hashlib
import json
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path


def review(folder):
    snapshots = json.loads((folder / 'source-snapshots.json').read_text(encoding='utf-8'))
    checks = {}
    for kind, source in snapshots.items():
        path = Path(source['path'])
        assert hashlib.sha256(path.read_bytes()).hexdigest() == source['sha256']
        with path.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
        if kind == 'superstore':
            totals = {key: sum((Decimal(row[col]) for row in rows), Decimal(0))
                      for key, col in [('metric-sales', 'Sales'), ('metric-profit', 'Profit')]}
            losses = [row for row in rows if Decimal(row['Profit']) < 0]
            regions = defaultdict(Decimal)
            for row in losses:
                regions[row['Region']] -= Decimal(row['Profit'])
            checks[kind] = {'rows': len(rows), 'totals': totals, 'loss_count': len(losses),
                            'loss_amount': sum(regions.values()), 'region_losses': dict(sorted(regions.items(), key=lambda x: -x[1]))}
        else:
            days, right = defaultdict(int), defaultdict(set)
            for row in rows:
                days[row['dteday']] += int(row['cnt'])
                right[row['dteday']].add(int(row['day__cnt']))
            assert all(len(values) == 1 for values in right.values()), 'Conflicting right-side daily values'
            diffs = {day: count - next(iter(right[day])) for day, count in days.items()}
            checks[kind] = {'rows': len(rows), 'totals': {'metric-quantity': sum(days.values())},
                'days_in_joined_snapshot': len(days), 'nonzero_daily_differences': sum(v != 0 for v in diffs.values()),
                'max_abs_daily_difference': max(abs(v) for v in diffs.values()),
                'duplicate_date_hour': len(rows) - len({(r['dteday'], r['hr']) for r in rows}),
                'boundary': 'Coverage within joined snapshot only; not proof of unmatched rows in original source tables.'}
    results = []
    for attempt in json.loads((folder / 'suite.json').read_text(encoding='utf-8')):
        case = attempt['case']
        answer = json.loads((folder / case / 'answer.json').read_text(encoding='utf-8'))
        meta = answer['message_meta']
        kind = 'superstore' if case.startswith('superstore') else 'bike'
        exact = checks[kind]['totals']
        totals_match = all(abs(Decimal(str(attempt['totals'][key])) - value) < Decimal('0.000001') for key, value in exact.items())
        failures = [{k: r.get(k) for k in ('step_id', 'tool', 'status', 'output_summary')}
                    for r in meta['tool_runs'] if r['status'] in ('failed', 'blocked')]
        stages = defaultdict(int)
        for call in attempt['usage']['calls']:
            stages[call['purpose']] += call['total_tokens']
        results.append({'case': case, 'original_status': attempt['status'], 'original_error': attempt.get('error'),
            'totals_match_independent_csv': totals_match, 'failed_tools': failures,
            'synthesis_status': (meta.get('synthesis_validation') or {}).get('status'),
            'synthesis_error': (meta.get('synthesis_validation') or {}).get('error'),
            'tokens_by_purpose': dict(stages), 'total_tokens': attempt['usage']['total_tokens'],
            'technical_status': 'degraded' if failures or (meta.get('synthesis_validation') or {}).get('status') != 'verified' else 'passed',
            'semantic_acceptance': 'requires_human_review; see docs/alpha-acceptance-2026-09-08.md'})
    adjudication = {'independent_source_checks': checks, 'cases': results,
                    'total_tokens': sum(r['total_tokens'] for r in results), 'original_attempts_preserved': True}
    destination = folder / 'adjudication.json'
    with destination.open('x', encoding='utf-8') as stream:
        json.dump(adjudication, stream, ensure_ascii=False, indent=2, default=str)
    print(json.dumps(adjudication, ensure_ascii=False, default=str))


if __name__ == '__main__':
    review(Path(sys.argv[1]).resolve())
