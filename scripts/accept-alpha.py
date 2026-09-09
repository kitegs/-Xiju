"""Five paid first attempts against an owned API and isolated copy. No hidden retries."""
import hashlib
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime

import httpx

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data'
CASES = [
    ('superstore-brief', 'superstore', '给管理者生成经营简报，只保留关键结论与少量图表，不做预测。日期无效时说明限制，不猜币种。', {'depth':'brief','focus':'general','audience':'manager'}),
    ('superstore-loss', 'superstore', '只生成亏损专题报告。定位负利润记录、亏损绝对额与区域集中项；不要泛泛销售排名，不做趋势或预测。解释必须有证据，相关性不是因果。', {'depth':'standard','focus':'loss','exclude_trend':True,'exclude_forecast':True}),
    ('superstore-detailed', 'superstore', '生成详细经营分析报告，核算销售额、利润、利润率，分解区域贡献，检查折扣与亏损关系。解释方法、口径、行动验证与限制，保留证据。不做预测；日期无效不得虚构趋势。', {'depth':'detailed','focus':'general','audience':'analyst','exclude_forecast':True}),
    ('bike-hourly', 'bike', '生成小时需求分析报告，重点比较时段和工作日。累计需求同时给出观测小时数、平均每观测小时需求；缺失小时不补零。不做预测，不把分类编码当连续变量回归。', {'depth':'standard','focus':'hourly','exclude_forecast':True}),
    ('bike-reconciliation', 'bike', '生成小时表与日表的多表核对报告。重点验证按日期汇总小时需求是否等于日表 cnt，给出差额、匹配覆盖、连接粒度和重复累计风险。不要泛泛经营建议，不做预测。右表日级字段不得对展开行求和。', {'depth':'detailed','focus':'general','exclude_forecast':True}),
]


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(destination):
    destination.mkdir(parents=True, exist_ok=False)
    with sqlite3.connect(f'file:{(SOURCE / "aibi-v2.db").as_posix()}?mode=ro', uri=True) as original, sqlite3.connect(destination / 'aibi-v2.db') as target:
        original.backup(target)
        target.row_factory = sqlite3.Row
        datasets = [dict(r) for r in target.execute('SELECT id,name,storage_key,workspace_id,current_version_id,semantics FROM datasets ORDER BY created_at DESC')]
        selected = {}
        for kind, name in [('superstore','Global Superstore'),('bike','Bike Sharing 小时与日级关联')]:
            selected[kind] = next(d for d in datasets if d['name'] == name)
        assert len({d['workspace_id'] for d in selected.values()}) == 1
        # No copied historic task is allowed to resume in the acceptance service.
        target.execute("UPDATE analysis_runs SET status='interrupted' WHERE status IN ('running','queued')")
        target.commit()
        snapshots = {}
        for kind, d in selected.items():
            key = Path(d['storage_key'])
            src = (SOURCE / key).resolve()
            dst = (destination / key).resolve()
            assert src.is_relative_to(SOURCE.resolve()) and dst.is_relative_to(destination.resolve())
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            snapshots[kind] = {'path': str(src), 'sha256': digest(src), 'dataset_version_id': d['current_version_id']}
            relation=target.execute('SELECT left_version_id,right_version_id FROM dataset_relationships WHERE result_dataset_id=?',(d['id'],)).fetchone()
            if relation:
                for version_id in relation:
                    parent=target.execute('SELECT storage_key FROM dataset_versions WHERE id=?',(version_id,)).fetchone()
                    parent_key=Path(parent[0]); parent_src=(SOURCE/parent_key).resolve(); parent_dst=(destination/parent_key).resolve()
                    assert parent_src.is_relative_to(SOURCE.resolve()) and parent_dst.is_relative_to(destination.resolve())
                    parent_dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(parent_src,parent_dst)
    shutil.copy2(SOURCE / '.vault-key', destination / '.vault-key')
    return selected, snapshots


def require(response):
    response.raise_for_status()
    return response.json()


def wait_run(client, wid, cid, run):
    deadline = time.monotonic() + 360
    while time.monotonic() < deadline:
        rows = require(client.get('/api/v1/analysis-runs', params={'workspace_id':wid,'conversation_id':cid}))
        current = next(row for row in rows if row['id'] == run['id'])
        if current['status'] not in {'running','queued'}:
            return current
        time.sleep(.5)
    client.post(f"/api/v1/analysis-runs/{run['id']}/cancel", params={'workspace_id':wid})
    raise TimeoutError('Acceptance deadline; cancellation requested, not retried')


def usage(database, cid):
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute('SELECT stage,purpose,model,prompt_tokens,completion_tokens,total_tokens,status,usage_unavailable FROM llm_usage_logs WHERE conversation_id=? ORDER BY created_at', (cid,))]
    return {'calls': rows, 'total_tokens':sum(r['total_tokens'] for r in rows),
            'complete_for_logged_responses':all(not r['usage_unavailable'] for r in rows)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',choices=[c[0] for c in CASES],help='Run one explicit paid recheck; original results remain untouched')
    args=parser.parse_args()
    output = SOURCE / 'acceptance' / datetime.now().strftime('%Y%m%d-%H%M%S-alpha')
    selected, snapshots = prepare(output / 'runtime')
    save(output / 'source-snapshots.json', snapshots)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port = sock.getsockname()[1]
    env = {**os.environ, 'AIBI_DATA_DIR':str(output / 'runtime')}
    env.pop('AIBI_DATABASE_URL', None)
    records = []
    with (output / 'api.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port)],
            cwd=ROOT / 'backend', env=env, stdout=log, stderr=log, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=40) as client:
                for _ in range(100):
                    if process.poll() is not None: raise RuntimeError('Isolated API failed; see api.log')
                    try:
                        if client.get('/api/v1/health').is_success: break
                    except httpx.HTTPError: pass
                    time.sleep(.2)
                wid = selected['superstore']['workspace_id']
                providers = require(client.get('/api/v1/settings/providers', params={'workspace_id':wid}))
                enabled = [p for p in providers if p['enabled'] and p.get('has_api_key')]
                assert len(enabled)==1 and enabled[0]['provider']=='deepseek', 'Only existing DeepSeek may be used'
                for name, kind, prompt, requirements in CASES:
                    if args.case and name!=args.case: continue
                    folder = output / name; folder.mkdir()
                    record = {'case':name, 'status':'failed', 'prompt':prompt, 'requirements':requirements}
                    cid = None
                    print('START '+name, flush=True)
                    try:
                        d = selected[kind]
                        caps = {'deep_analysis':True,'max_rounds':3,'content_review':True,'chart_layout':True,'alternatives':False}
                        conversation = require(client.post('/api/v1/conversations',json={'workspace_id':wid,'dataset_id':d['id'], 'title':name,'clarification_mode':'off','analysis_capabilities':caps}))
                        cid = conversation['id']; record['conversation_id']=cid
                        run = require(client.post('/api/v1/chat/plan-async',json={'workspace_id':wid,'conversation_id':cid,'dataset_id':d['id'],
                            'message':prompt,'execution_mode':'partial','analysis_options':{'include_report':True,'include_recommendations':True,'show_code':True,'capabilities':caps,'report_requirements':requirements}}))
                        planned = wait_run(client,wid,cid,run); save(folder/'planning-run.json',planned)
                        assert planned['status']=='completed', planned.get('error')
                        messages = require(client.get(f'/api/v1/conversations/{cid}/messages'))
                        message = next(m for m in messages if m['id']==planned['result_message_id'])
                        save(folder/'plan.json',message)
                        record['planning']=message['message_meta'].get('planning')
                        record['tools']=[s['tool'] for s in message['message_meta']['analysis_plan']['steps']]
                        run = require(client.post('/api/v1/chat/execute-async',json={'workspace_id':wid,'conversation_id':cid,'plan_message_id':message['id'],'approved':True}))
                        executed = wait_run(client,wid,cid,run); save(folder/'execution-run.json',executed)
                        assert executed['status']=='completed', executed.get('error')
                        messages = require(client.get(f'/api/v1/conversations/{cid}/messages'))
                        answer = next(m for m in messages if m['id']==executed['result_message_id'])
                        save(folder/'answer.json',answer)
                        meta = answer['message_meta']
                        record['synthesis_validation']=meta.get('synthesis_validation')
                        record['component_results']=meta.get('component_results')
                        assert executed['report_id'], 'No report'
                        report = require(client.get(f"/api/v1/reports/{executed['report_id']}")); save(folder/'report.json',report)
                        doc = report['document']; record['report_id']=report['id']
                        record['quality']=doc.get('quality'); record['blocks']=len(doc['blocks']); record['charts']=len(doc['charts'])
                        ev = {e['id']:e for e in doc['evidence']}
                        expected = {'metric-sales':12642905.0,'metric-profit':1467457.29} if kind=='superstore' else {'metric-quantity':3292679}
                        record['totals']={k:ev[k]['calculation']['result'] for k in expected}
                        assert all(round(record['totals'][k], 2)==v for k,v in expected.items()), 'Rounded totals mismatch'
                        errors=[c for c in meta.get('component_results',[]) + meta.get('tool_runs',[]) if c.get('status') in {'failed','blocked'}]
                        record['failed_tools'] = [{k: e.get(k) for k in ('tool','status','output_summary','error')} for e in errors]
                        record['status']='passed' if (record['planning'] or {}).get('provider')=='deepseek' and (record['synthesis_validation'] or {}).get('status')=='verified' and doc['quality']['passed'] and not errors else 'degraded'
                    except Exception as exc:
                        record['error']=f'{type(exc).__name__}: {str(exc)[:800]}'
                    finally:
                        record['usage']=usage(output/'runtime/aibi-v2.db',cid) if cid else {}
                        record['source_unchanged']=digest(Path(snapshots[kind]['path']))==snapshots[kind]['sha256']
                        save(folder/'acceptance.json',record); records.append(record)
                        save(output/'suite.json',records)
                        print(json.dumps({k:record.get(k) for k in ('case','status','error','blocks','charts','usage')},ensure_ascii=False),flush=True)
        finally:
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
    print('RESULT '+str(output),flush=True)


if __name__=='__main__': main()
