from fastapi.testclient import TestClient
from app.main import app


def test_conversation_delete_archives_and_restore_preserves_messages():
    with TestClient(app) as client:
        workspace = client.post('/api/v1/workspaces/bootstrap').json()['id']
        conversation = client.post('/api/v1/conversations', json={'workspace_id': workspace, 'title': '保留记录'}).json()
        cid = conversation['id']
        import asyncio
        from app.database import SessionLocal
        from app.models import ChatMessage
        async def seed():
            async with SessionLocal() as session:
                session.add(ChatMessage(conversation_id=cid, role='user', content='不可丢失的分析记录', message_meta={}))
                await session.commit()
        asyncio.run(seed())
        before = client.get(f'/api/v1/conversations/{cid}/messages').json()
        assert before[0]['content'] == '不可丢失的分析记录'
        assert client.delete(f'/api/v1/conversations/{cid}').status_code == 204
        assert not client.get('/api/v1/conversations', params={'workspace_id':workspace}).json()
        archived = client.get('/api/v1/conversations', params={'workspace_id':workspace,'archived':True}).json()
        assert archived[0]['id'] == cid and archived[0]['archived'] is True
        assert client.get(f'/api/v1/conversations/{cid}/messages').json() == before
        assert client.post(f'/api/v1/conversations/{cid}/restore').json()['archived'] is False
        assert client.get('/api/v1/conversations', params={'workspace_id':workspace}).json()[0]['id'] == cid
