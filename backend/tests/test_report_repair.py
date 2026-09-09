from fastapi.testclient import TestClient
from app.main import app


def test_repair_accepts_browser_integer_serialization_but_not_changed_chart_values():
    import pandas as pd
    from app.services import build_report, profile_dataframe
    from app.report_repair import repair_candidate
    frame = pd.DataFrame({"Sales": [10, 20], "Region": ["A", "B"]})
    fresh = build_report(frame, profile_dataframe(frame), "测试", "报告")
    original = fresh.model_copy(deep=True)
    chart = next(item for item in original.charts if item.chart_type == 'kpi')
    chart.data[0]["value"] = int(chart.data[0]["value"])
    candidate, _ = repair_candidate(original, fresh)
    check = next(c for c in candidate.quality.claim_checks if c['target_kind'] == 'chart' and c['target_id'] == chart.id)
    assert check['status'] == 'verified'
    chart.data[0]["value"] = 999
    candidate, _ = repair_candidate(original, fresh)
    assert any(c['status'] == 'unverified' for c in candidate.quality.claim_checks if c['target_kind'] == 'chart')


def test_repair_rejects_missing_version_and_changed_source(monkeypatch):
    import app.report_repair as repair
    with TestClient(app) as client:
        wid=client.post('/api/v1/workspaces/bootstrap').json()['id']
        rid=client.post('/api/v1/reports',json={'workspace_id':wid}).json()['id']
        assert client.post(f'/api/v1/reports/{rid}/repair/preview').status_code==409
        dataset=client.post('/api/v1/samples/retail-sales-2026/import',params={'workspace_id':wid}).json()
        rid=client.post('/api/v1/analysis/run',json={'workspace_id':wid,'dataset_id':dataset['id']}).json()['report_id']
        monkeypatch.setattr(repair,'_sha256',lambda path:'changed')
        result=client.post(f'/api/v1/reports/{rid}/repair/preview')
        assert result.status_code==409 and '哈希' in result.text


def test_repair_preview_is_readonly_and_confirmation_restores_only_supported_content():
    with TestClient(app) as client:
        wid=client.post('/api/v1/workspaces/bootstrap').json()['id']
        dataset=client.post('/api/v1/samples/retail-sales-2026/import',params={'workspace_id':wid}).json()
        rid=client.post('/api/v1/analysis/run',json={'workspace_id':wid,'dataset_id':dataset['id']}).json()['report_id']
        doc=client.get(f'/api/v1/reports/{rid}').json()['document']
        doc['findings'][0]['statement']='销售额是 999999999 元。'
        doc['blocks'].append({'id':'custom','kind':'paragraph','content':'我的手工解释仍需核验。','evidence_ids':[]})
        doc['blocks'].reverse()
        edited=client.put(f'/api/v1/reports/{rid}',json={'title':'编辑稿','document':doc}).json()['document']
        versions=len(client.get(f'/api/v1/reports/{rid}/versions').json())
        response=client.post(f'/api/v1/reports/{rid}/repair/preview')
        assert response.status_code==200,response.text
        proposal=response.json()
        assert proposal['changes']
        assert client.get(f'/api/v1/reports/{rid}').json()['document']['findings'][0]['statement']==edited['findings'][0]['statement']
        assert len(client.get(f'/api/v1/reports/{rid}/versions').json())==versions
        assert client.post(f'/api/v1/reports/{rid}/repair/apply',json={'proposal_hash':proposal['proposal_hash'],'approved':False}).status_code==422
        applied=client.post(f'/api/v1/reports/{rid}/repair/apply',json={'proposal_hash':proposal['proposal_hash'],'approved':True})
        assert applied.status_code==200,applied.text
        saved=client.get(f'/api/v1/reports/{rid}').json()['document']
        assert '999999999' not in saved['findings'][0]['statement']
        assert [b['id'] for b in saved['blocks']]==[b['id'] for b in edited['blocks']]
        assert saved['blocks'][0]['content']=='我的手工解释仍需核验。'
        assert not saved['quality']['passed']
        assert len(client.get(f'/api/v1/reports/{rid}/versions').json())==versions+1
        assert client.post(f'/api/v1/reports/{rid}/repair/apply',json={'proposal_hash':proposal['proposal_hash'],'approved':True}).status_code==409
        proposal=client.post(f'/api/v1/reports/{rid}/repair/preview').json()
        client.patch(f'/api/v1/reports/{rid}',json={'title':'预览后再修改标题'})
        assert client.post(f'/api/v1/reports/{rid}/repair/apply',json={'proposal_hash':proposal['proposal_hash'],'approved':True}).status_code==409
