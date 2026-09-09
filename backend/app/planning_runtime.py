"""Queued planning shares the Run lifecycle but never executes the plan."""
from types import SimpleNamespace
from fastapi import HTTPException
from .models import AnalysisRun, Dataset
from .schemas import ChatPlanRequest


async def dispatch(payload, actor, session, run_id, *, plan, execute):
    run=await session.get(AnalysisRun,run_id) if run_id else None
    if not run or (run.analysis_spec or {}).get('kind')!='planning':
        return await execute(payload,actor,session,run_id)
    request=ChatPlanRequest.model_validate(run.analysis_spec['request'])
    if request.dataset_id and run.dataset_version_ids:
        dataset=await session.get(Dataset,request.dataset_id)
        if not dataset or dataset.current_version_id not in run.dataset_version_ids:
            raise HTTPException(409,'规划等待期间数据版本已改变，请重新规划')
    request.resume_message_id=run.plan_message_id
    result=await plan(request,actor,session)
    return SimpleNamespace(assistant_message=result.user_message,report_id=None)
