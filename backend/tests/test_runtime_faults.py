import asyncio
import time
import httpx
import pytest
from fastapi.testclient import TestClient
from app.main import app


def setup_case(client):
    wid=client.post('/api/v1/workspaces/bootstrap').json()['id']
    cid=client.post('/api/v1/conversations',json={'workspace_id':wid,'clarification_mode':'off'}).json()['id']
    return wid,cid


def state(client,wid,cid,rid):
    return next(r for r in client.get('/api/v1/analysis-runs',params={'workspace_id':wid,'conversation_id':cid}).json() if r['id']==rid)


def wait_state(client,wid,cid,rid,wanted):
    for _ in range(100):
        current=state(client,wid,cid,rid)
        if current['status'] in wanted: return current
        time.sleep(.02)
    raise AssertionError(current)


def test_repeated_planning_retry_reuses_one_run_and_placeholder(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main,'_schedule_run',lambda *args:None)
    with TestClient(app) as client:
        wid,cid=setup_case(client)
        run=client.post('/api/v1/chat/plan-async',json={'workspace_id':wid,'conversation_id':cid,'message':'说明如何分析'}).json()
        client.post(f"/api/v1/analysis-runs/{run['id']}/cancel",params={'workspace_id':wid})
        first=client.post(f"/api/v1/analysis-runs/{run['id']}/retry",params={'workspace_id':wid})
        second=client.post(f"/api/v1/analysis-runs/{run['id']}/retry",params={'workspace_id':wid})
        assert first.status_code==second.status_code==202
        assert first.json()['id']==second.json()['id']
        assert first.json()['attempt']==2
        assert len(client.get(f'/api/v1/conversations/{cid}/messages').json())==2


@pytest.mark.parametrize('kind',['planning','execution'])
def test_running_work_cancellation_is_durable_and_not_completed(monkeypatch,kind):
    import app.main as main
    async def waiting(*args,**kwargs): await asyncio.sleep(60)
    with TestClient(app) as client:
        wid,cid=setup_case(client)
        if kind=='planning':
            monkeypatch.setattr(main,'plan_chat',waiting)
            run=client.post('/api/v1/chat/plan-async',json={'workspace_id':wid,'conversation_id':cid,'message':'说明如何分析'}).json()
        else:
            plan=client.post('/api/v1/chat/plan',json={'workspace_id':wid,'conversation_id':cid,'message':'说明如何分析'}).json()
            monkeypatch.setattr(main,'_execute_chat_plan',waiting)
            run=client.post('/api/v1/chat/execute-async',json={'workspace_id':wid,'conversation_id':cid,'plan_message_id':plan['user_message']['id']}).json()
        wait_state(client,wid,cid,run['id'],{'running'})
        assert client.post(f"/api/v1/analysis-runs/{run['id']}/cancel",params={'workspace_id':wid}).status_code==200
        stopped=wait_state(client,wid,cid,run['id'],{'cancelled'})
        assert stopped['report_id'] is None and stopped['result_message_id'] is None
        events=client.get(f"/api/v1/analysis-runs/{run['id']}/events",params={'workspace_id':wid}).json()
        assert 'run.completed' not in [e['event_type'] for e in events]
        assert client.get(f'/api/v1/conversations/{cid}/messages').json()


def test_model_network_failure_is_explicit_degradation(monkeypatch):
    import app.main as main
    async def disconnected(*args,**kwargs): raise httpx.ConnectError('injected network unavailable')
    monkeypatch.setattr(main,'complete',disconnected)
    with TestClient(app) as client:
        wid,cid=setup_case(client)
        dataset=client.post('/api/v1/samples/retail-sales-2026/import',params={'workspace_id':wid}).json()
        client.put('/api/v1/settings/providers/deepseek',params={'workspace_id':wid},json={
            'enabled':True,'is_default':True,'base_url':'https://api.deepseek.com','model':'offline-test','api_key':'test-only-key','options':{}})
        plan=client.post('/api/v1/chat/plan',json={'workspace_id':wid,'conversation_id':cid,'dataset_id':dataset['id'],'message':'生成分析报告'}).json()
        assert plan['user_message']['message_meta']['planning']['provider']=='deepseek-fallback'
        result=client.post('/api/v1/chat/execute',json={'workspace_id':wid,'conversation_id':cid,'plan_message_id':plan['user_message']['id'],'approved':True}).json()
        assert result['provider']=='deepseek-fallback'
        assert result['assistant_message']['message_meta']['synthesis_validation']['status']=='degraded'
        assert result['assistant_message']['message_meta']['execution_outcome']['status']=='degraded'
        report=client.get(f"/api/v1/reports/{result['report_id']}").json()
        assert not report['document']['quality']['passed']


def test_failed_tool_marks_draft_and_run_degraded(monkeypatch):
    def broken_layout(*args, **kwargs): raise RuntimeError('injected layout failure')
    import app.extensions as extensions
    monkeypatch.setattr(extensions, 'execute_builtin', broken_layout)
    with TestClient(app) as client:
        wid,cid=setup_case(client)
        dataset=client.post('/api/v1/samples/retail-sales-2026/import',params={'workspace_id':wid}).json()
        plan=client.post('/api/v1/chat/plan',json={'workspace_id':wid,'conversation_id':cid,'dataset_id':dataset['id'],'message':'生成报告'}).json()
        run=client.post('/api/v1/chat/execute-async',json={'workspace_id':wid,'conversation_id':cid,'plan_message_id':plan['user_message']['id'],'approved':True}).json()
        result=wait_state(client,wid,cid,run['id'],{'completed','failed'})
        assert result['status']=='completed' and result['progress']['outcome']=='degraded'
        report=client.get(f"/api/v1/reports/{result['report_id']}").json()
        assert not report['document']['quality']['passed']
        assert any(i['id']=='execution-degraded' for i in report['document']['quality']['issues'])


def test_repeated_execution_retry_produces_one_report_artifact(monkeypatch):
    import app.main as main
    schedule = main._schedule_run
    monkeypatch.setattr(main, '_schedule_run', lambda *args: None)
    with TestClient(app) as client:
        wid,cid=setup_case(client)
        dataset=client.post('/api/v1/samples/retail-sales-2026/import',params={'workspace_id':wid}).json()
        plan=client.post('/api/v1/chat/plan',json={'workspace_id':wid,'conversation_id':cid,'dataset_id':dataset['id'],'message':'生成报告'}).json()
        run=client.post('/api/v1/chat/execute-async',json={'workspace_id':wid,'conversation_id':cid,'plan_message_id':plan['user_message']['id'],'approved':True}).json()
        client.post(f"/api/v1/analysis-runs/{run['id']}/cancel",params={'workspace_id':wid})
        monkeypatch.setattr(main, '_schedule_run', schedule)
        endpoint=f"/api/v1/analysis-runs/{run['id']}/retry"
        first=client.post(endpoint,params={'workspace_id':wid}).json()
        second=client.post(endpoint,params={'workspace_id':wid}).json()
        assert first['id']==second['id']
        result=wait_state(client,wid,cid,first['id'],{'completed','failed'})
        assert result['status']=='completed'
        third=client.post(endpoint,params={'workspace_id':wid}).json()
        assert third['id']==first['id']
        artifacts=client.get(f"/api/v1/projects/{dataset['project_id']}/artifacts").json()
        reports=[a for a in artifacts if a['run_id']==first['id'] and a['kind']=='report']
        assert len(reports)==1 and reports[0]['version']==1
        message=client.get(f'/api/v1/conversations/{cid}/messages').json()[-1]
        layout=next(r for r in message['message_meta']['component_results'] if r['tool']=='report.layout')
        assert layout['result']['extension']['id']=='builtin.report-layout'
