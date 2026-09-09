"""Offline semantic checks of recorded live responses; never overwrite attempts."""
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.schemas import ReportDocument
from app.report_requirements import synchronize_action_blocks
from app.report_claims import seal_claims
from app.services import assess_report_quality


def verify(folder):
    results=[]
    output=folder/('delivery-review-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    output.mkdir()
    for attempt in json.loads((folder/'suite.json').read_text(encoding='utf-8')):
        case=attempt['case']; sub=folder/case
        report=json.loads((sub/'report.json').read_text(encoding='utf-8'))
        answer=json.loads((sub/'answer.json').read_text(encoding='utf-8'))['message_meta']
        doc=ReportDocument.model_validate(report['document'])
        # Validate the final deterministic presentation fix on a separate candidate.
        synchronize_action_blocks(doc); seal_claims(doc); doc.quality=assess_report_quality(doc)
        tools=[s['tool'] for s in answer['tool_runs']]
        assert not any(s['status'] in {'failed','blocked'} for s in answer['tool_runs'])
        assert all(i<tools.index('report.build') for i,t in enumerate(tools) if t in {'sql.query','analysis.deepen','data.reconcile'})
        assert answer['synthesis_validation']['status']=='verified'
        facts={e.id:e for e in doc.evidence}
        if case=='superstore-brief': assert len(doc.charts)<=3
        if case=='superstore-detailed':
            assert len(doc.charts)>3
            assert any(b.id.startswith('result-sql-') for b in doc.blocks)
            assert all('增长与稳定性' not in b.content for b in doc.blocks)
        if case=='superstore-loss':
            assert abs(facts['loss-amount'].calculation['result']-920646.15572)<1e-6
            assert facts['loss-count'].calculation['result']==12544
            assert facts['loss-groups'].data[0]['Region']=='Central'
            assert abs(facts['sql-loss-summary'].data[0]['loss_record_ratio']-12544/51290)<1e-10
            assert all(e.get('scope',{}).get('filter',{}).get('operator')=='lt' or "'operator': 'lt'" in e.get('code','') for e in answer['evidence'] if e['id'].startswith('deep-'))
            assert any('mean_discount=' in b.content for b in doc.blocks)
            assert all('增长与稳定性' not in b.content for b in doc.blocks)
        if case=='bike-hourly':
            joint=facts['hourly-workday-joint']
            assert len(joint.data)==24 and [r['hr'] for r in joint.data]==list(range(24))
            assert all('工作日' in r and '非工作日' in r for r in joint.data)
        if case=='bike-reconciliation':
            raw=next(e for e in answer['evidence'] if e['id']=='reconciliation-by-key')
            if 'verified_scope' not in raw:
                # Older response projection dropped extra fields; durable step events retain them.
                run=json.loads((sub/'execution-run.json').read_text(encoding='utf-8'))
                with sqlite3.connect(f'file:{(folder/"runtime/aibi-v2.db").as_posix()}?mode=ro',uri=True) as conn:
                    events=[json.loads(row[0]) for row in conn.execute("SELECT data FROM run_events WHERE run_id=? AND event_type='step.completed'",(run['id'],))]
                raw=next(e for event in events for e in event.get('evidence',[]) if e['id']=='reconciliation-by-key')
            assert raw['verified_scope']=={'keys':['dteday'],'matched':731,'left_only':0,'right_only':0,'mismatches':0,'max_abs_difference':0.0}
            assert not doc.charts and any('reconciliation' in f.id for f in doc.findings)
        assert not [i for i in doc.quality.issues if i.severity=='error'], doc.quality
        candidate=output/(case+'.json')
        with candidate.open('x',encoding='utf-8') as out:json.dump(doc.model_dump(mode='json'),out,ensure_ascii=False,indent=2)
        results.append({'case':case,'semantic_checks':'passed','quality_passed':doc.quality.passed,'candidate':str(candidate),'original_status':attempt['status'],'offline_model_tokens':0})
    with (output/'summary.json').open('x',encoding='utf-8') as out:json.dump(results,out,ensure_ascii=False,indent=2)
    print(json.dumps(results,ensure_ascii=False))


if __name__=='__main__':verify(Path(sys.argv[1]).resolve())
