from fastapi.testclient import TestClient
from app.main import app


def test_report_crud_preserves_versions_and_recycles_without_deleting_data():
    with TestClient(app) as client:
        workspace = client.post('/api/v1/workspaces/bootstrap').json()['id']
        dataset = client.post('/api/v1/samples/retail-sales-2026/import', params={'workspace_id':workspace}).json()
        created = client.post('/api/v1/reports', json={'workspace_id':workspace,'title':'原报告','dataset_id':dataset['id']})
        assert created.status_code == 201, created.text
        report = created.json()
        assert report['project_id'] and report['dataset_version_id']
        doc = report['document']
        doc['summary'] = '人工说明'
        assert client.put(f"/api/v1/reports/{report['id']}",json={'title':'已编辑','document':doc}).status_code == 200
        copy = client.post('/api/v1/reports',json={'workspace_id':workspace,'title':'副本','source_report_id':report['id']}).json()
        assert copy['id'] != report['id'] and copy['document']['summary'] == '人工说明'
        assert copy['dataset_version_id'] == report['dataset_version_id']
        renamed = client.patch(f"/api/v1/reports/{report['id']}",json={'title':'重新命名'}).json()
        assert renamed['title'] == renamed['document']['title'] == '重新命名'
        assert len(client.get(f"/api/v1/reports/{report['id']}/versions").json()) == 2
        for _ in range(2):
            assert client.delete(f"/api/v1/reports/{report['id']}").status_code == 204
        assert client.get(f"/api/v1/reports/{report['id']}").status_code == 410
        assert client.patch(f"/api/v1/reports/{report['id']}",json={'title':'不允许修改'}).status_code == 410
        active = client.get('/api/v1/reports',params={'workspace_id':workspace}).json()
        assert [r['id'] for r in active] == [copy['id']]
        trash = client.get('/api/v1/reports',params={'workspace_id':workspace,'deleted':True}).json()
        assert [r['id'] for r in trash] == [report['id']]
        assert client.post(f"/api/v1/reports/{report['id']}/restore").status_code == 200
        assert client.get(f"/api/v1/reports/{report['id']}").json()['document']['summary'] == '人工说明'
        assert client.get('/api/v1/datasets',params={'workspace_id':workspace}).json()[0]['id'] == dataset['id']
        assert client.post('/api/v1/reports',json={'workspace_id':workspace,'title':'   '}).status_code == 422
        assert client.post('/api/v1/reports',json={'workspace_id':workspace,'dataset_id':'missing'}).status_code == 404
