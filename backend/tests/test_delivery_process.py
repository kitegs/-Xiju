"""Hard-exit tests at delivery transaction boundaries, using owned local processes."""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
import httpx
import pytest


@pytest.mark.parametrize('stage',['report-flushed','artifact-flushed','before-delivery-commit','after-delivery-commit'])
def test_delivery_survives_process_exit_without_duplicate_artifact(tmp_path,stage):
    backend=Path(__file__).resolve().parents[1]
    env={**os.environ,'AIBI_DATA_DIR':str(tmp_path/'runtime'),'PYTHONPATH':str(backend)}
    env.pop('AIBI_DATABASE_URL',None)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    process=None
    with (tmp_path/'child.log').open('w') as log, httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=10) as client:
        def start(fault):
            args=[str(Path(__file__).resolve()),str(port),stage] if fault else ['-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port)]
            proc=subprocess.Popen([sys.executable,*args],cwd=backend,env=env,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            for _ in range(150):
                assert proc.poll() is None
                try:
                    if client.get('/api/v1/health').is_success:return proc
                except httpx.HTTPError:pass
                time.sleep(.1)
            proc.kill();proc.wait();raise AssertionError('Test server did not start')
        def runs():
            return {r['id']:r for r in client.get('/api/v1/analysis-runs',params={'workspace_id':wid,'conversation_id':cid}).json()}
        try:
            process=start(True)
            wid=client.post('/api/v1/workspaces/bootstrap').json()['id']
            dataset=client.post('/api/v1/samples/retail-sales-2026/import',params={'workspace_id':wid}).json()
            cid=client.post('/api/v1/conversations',json={'workspace_id':wid,'dataset_id':dataset['id'],'clarification_mode':'off'}).json()['id']
            message=client.post('/api/v1/chat/plan',json={'workspace_id':wid,'conversation_id':cid,'dataset_id':dataset['id'],'message':'生成报告'}).json()['user_message']
            first=client.post('/api/v1/chat/execute-async',json={'workspace_id':wid,'conversation_id':cid,'plan_message_id':message['id'],'approved':True}).json()
            assert process.wait(timeout=30)==73
            process=start(False)
            current=runs()[first['id']]
            if stage=='after-delivery-commit':
                assert current['status']=='completed' and current['result_message_id']
                assert client.post(f"/api/v1/analysis-runs/{first['id']}/retry",params={'workspace_id':wid}).status_code==409
            else:
                assert current['status']=='interrupted' and not current['result_message_id']
                if current['report_id']:
                    draft=client.get(f"/api/v1/reports/{current['report_id']}").json()
                    assert not draft['document']['quality']['passed']
                retry=client.post(f"/api/v1/analysis-runs/{first['id']}/retry",params={'workspace_id':wid}).json()
                for _ in range(200):
                    current=runs()[retry['id']]
                    if current['status'] not in {'queued','running'}:break
                    time.sleep(.1)
                assert current['status']=='completed',current
            artifacts=client.get(f"/api/v1/projects/{dataset['project_id']}/artifacts").json()
            assert len([a for a in artifacts if a['kind']=='report'])==1
            messages=client.get(f'/api/v1/conversations/{cid}/messages').json()
            assert len([m for m in messages if m['role']=='assistant'])==1
            reports=client.get('/api/v1/reports',params={'workspace_id':wid}).json()
            assert len(reports)==1
        finally:
            if process and process.poll() is None:process.kill();process.wait(timeout=10)


if __name__=='__main__':
    import uvicorn
    from app import delivery
    async def crash(stage):
        if stage==sys.argv[2]:os._exit(73)
    delivery.checkpoint=crash
    uvicorn.run('app.main:app',host='127.0.0.1',port=int(sys.argv[1]))
