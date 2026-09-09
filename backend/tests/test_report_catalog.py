from fastapi.testclient import TestClient
from app.main import app


def test_report_catalog_is_bounded_searchable_and_does_not_return_documents():
    with TestClient(app) as client:
        wid = client.post('/api/v1/workspaces/bootstrap').json()['id']
        ids = []
        for title in ['Catalog C', 'Catalog A', 'Catalog B']:
            response = client.post('/api/v1/reports', json={'workspace_id': wid, 'title': title})
            assert response.status_code == 201
            ids.append(response.json()['id'])
        params = {'workspace_id': wid, 'sort': 'title_asc', 'limit': 2}
        first = client.get('/api/v1/report-catalog', params=params).json()
        assert first['total'] == 3 and first['has_more']
        assert [r['title'] for r in first['items']] == ['Catalog A', 'Catalog B']
        assert all('document' not in r and 'chart_count' in r for r in first['items'])
        second = client.get('/api/v1/report-catalog', params={**params, 'offset': 2}).json()
        assert [r['title'] for r in second['items']] == ['Catalog C']
        assert not second['has_more']
        searched = client.get('/api/v1/report-catalog', params={**params, 'q': 'Catalog B'}).json()
        assert searched['total'] == 1
        client.delete(f'/api/v1/reports/{ids[0]}')
        assert client.get('/api/v1/report-catalog', params=params).json()['total'] == 2
        assert client.get('/api/v1/report-catalog', params={**params, 'deleted': True}).json()['total'] == 1
        assert client.get('/api/v1/report-catalog', params={**params, 'limit': 101}).status_code == 422
        assert client.get('/api/v1/reports', params={'workspace_id': wid}).json()[0]['document']
