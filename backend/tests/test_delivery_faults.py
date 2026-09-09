from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from app.main import app


def test_concurrent_planning_and_retry_are_single_admission(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main,'_schedule_run',lambda *args:None)
    with TestClient(app) as client:
        wid=client.post('/api/v1/workspaces/bootstrap').json()['id']
        cid=client.post('/api/v1/conversations',json={'workspace_id':wid,'clarification_mode':'off'}).json()['id']
        payload={'workspace_id':wid,'conversation_id':cid,'message':'说明分析步骤','idempotency_key':'concurrent-first'}
        with ThreadPoolExecutor(max_workers=5) as pool:
            responses=list(pool.map(lambda _:client.post('/api/v1/chat/plan-async',json=payload),range(5)))
        assert all(r.status_code==202 for r in responses)
        ids={r.json()['id'] for r in responses}; assert len(ids)==1
        rid=ids.pop()
        conflict=client.post('/api/v1/chat/plan-async',json={**payload,'message':'不同内容'})
        assert conflict.status_code==409
        client.post(f'/api/v1/analysis-runs/{rid}/cancel',params={'workspace_id':wid})
        with ThreadPoolExecutor(max_workers=5) as pool:
            retries=list(pool.map(lambda _:client.post(f'/api/v1/analysis-runs/{rid}/retry',params={'workspace_id':wid}),range(5)))
        assert all(r.status_code==202 for r in retries)
        assert len({r.json()['id'] for r in retries})==1
        assert len(client.get(f'/api/v1/conversations/{cid}/messages').json())==2


def test_concurrent_execution_enqueues_once(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main,'_schedule_run',lambda *args:None)
    with TestClient(app) as client:
        wid=client.post('/api/v1/workspaces/bootstrap').json()['id']
        cid=client.post('/api/v1/conversations',json={'workspace_id':wid,'clarification_mode':'off'}).json()['id']
        message=client.post('/api/v1/chat/plan',json={'workspace_id':wid,'conversation_id':cid,'message':'说明分析步骤'}).json()['user_message']
        payload={'workspace_id':wid,'conversation_id':cid,'plan_message_id':message['id'],'approved':True}
        with ThreadPoolExecutor(max_workers=5) as pool:
            responses=list(pool.map(lambda _:client.post('/api/v1/chat/execute-async',json=payload),range(5)))
        assert all(r.status_code==202 for r in responses)
        assert len({r.json()['id'] for r in responses})==1
