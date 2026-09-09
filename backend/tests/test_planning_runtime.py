import time
from fastapi.testclient import TestClient
from app.main import app


def test_queued_planning_completes_without_executing_tools():
    with TestClient(app) as client:
        wid = client.post('/api/v1/workspaces/bootstrap').json()['id']
        cid = client.post('/api/v1/conversations', json={'workspace_id': wid, 'clarification_mode': 'off'}).json()['id']
        response = client.post('/api/v1/chat/plan-async', json={
            'workspace_id': wid, 'conversation_id': cid, 'message': '告诉我如何开始分析'})
        assert response.status_code == 202, response.text
        run = response.json()
        for _ in range(100):
            rows = client.get('/api/v1/analysis-runs', params={'workspace_id': wid, 'conversation_id': cid}).json()
            run = next(row for row in rows if row['id'] == run['id'])
            if run['status'] not in {'queued', 'running'}: break
            time.sleep(.03)
        assert run['status'] == 'completed', run
        assert run['report_id'] is None
        messages = client.get(f'/api/v1/conversations/{cid}/messages').json()
        assert len(messages) == 1
        assert messages[0]['message_meta']['analysis_plan']['status'] == 'pending'


def test_queued_planning_can_be_cancelled_without_execution(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, '_schedule_run', lambda *args: None)
    with TestClient(app) as client:
        wid = client.post('/api/v1/workspaces/bootstrap').json()['id']
        cid = client.post('/api/v1/conversations', json={'workspace_id': wid}).json()['id']
        run = client.post('/api/v1/chat/plan-async', json={
            'workspace_id': wid, 'conversation_id': cid, 'message': '生成报告'}).json()
        result = client.post(f"/api/v1/analysis-runs/{run['id']}/cancel", params={'workspace_id': wid})
        assert result.status_code == 200, result.text
        assert result.json()['status'] == 'cancelled'
        assert result.json()['report_id'] is None
