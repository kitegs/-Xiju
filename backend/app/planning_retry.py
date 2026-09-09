"""Atomic retry identity for one planning attempt; no scheduling before commit."""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .models import AnalysisRun, ChatMessage


async def prepare_retry(session, previous):
    key = f'planning-retry:{previous.id}'
    existing = await session.scalar(select(AnalysisRun).where(AnalysisRun.idempotency_key == key))
    if existing:
        return existing, False
    try:
        async with session.begin_nested():
            request = previous.analysis_spec['request']
            message = ChatMessage(conversation_id=previous.conversation_id, role='user',
                                  content=request['message'], message_meta={'planning_job':True})
            session.add(message)
            await session.flush()
            run = AnalysisRun(workspace_id=previous.workspace_id, project_id=previous.project_id,
                conversation_id=previous.conversation_id, plan_message_id=message.id,
                analysis_spec=previous.analysis_spec, dataset_version_ids=previous.dataset_version_ids,
                idempotency_key=key, attempt=previous.attempt+1, status='queued')
            session.add(run)
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(select(AnalysisRun).where(AnalysisRun.idempotency_key == key))
        if not existing: raise
        return existing, False
    return run, True
