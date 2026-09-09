"""Local background lifecycle; scheduling remains composed by the application."""
import asyncio
from datetime import datetime, timezone
from .models import AnalysisRun
from .schemas import ChatExecuteRequest
from .domain import transition_run

class RunCancelled(Exception):
    pass


async def run_background(run_id: str, actor_id: str | None, *, session_factory, execute, append_event) -> None:
    async with session_factory() as task_session:
        run = await task_session.get(AnalysisRun, run_id)
        if not run or run.status != "queued":
            return
        transition_run(run, "running")
        run.started_at = datetime.now(timezone.utc)
        run.progress = {"current_step": None, "completed_steps": 0, "total_steps": 0}
        await append_event(task_session, run.id, "run.started", "running", "分析任务开始执行")
        await task_session.commit()
        try:
            result = await execute(
                ChatExecuteRequest(
                    workspace_id=run.workspace_id, conversation_id=run.conversation_id,
                    plan_message_id=run.plan_message_id, approved=run.approval_granted,
                ),
                actor_id, task_session, run_id,
            )
            run = await task_session.get(AnalysisRun, run_id)
            if run and run.status=='running':
                transition_run(run, "completed")
                run.result_message_id = result.assistant_message.id
                run.report_id = result.report_id
                meta = getattr(result.assistant_message, 'message_meta', {}) or {}
                outcome = meta.get('execution_outcome', {})
                degraded = outcome.get('status') == 'degraded' or 'fallback' in (meta.get('planning', {}).get('provider') or '')
                run.progress = {**(run.progress or {}), "completed_steps": (run.progress or {}).get("total_steps", 0), "current_step": None,
                                "outcome": "degraded" if degraded else "completed"}
                run.finished_at = datetime.now(timezone.utc)
                await append_event(
                    task_session, run.id, "run.completed", "completed", "运行已结束，存在失败或降级，需复核" if degraded else "分析任务已完成",
                    data={"result_message_id": run.result_message_id, "report_id": run.report_id, "outcome": run.progress['outcome']},
                )
                await task_session.commit()
        except (RunCancelled, asyncio.CancelledError):
            await task_session.rollback()
            run = await task_session.get(AnalysisRun, run_id)
            if run and run.status=='running':
                transition_run(run, "cancelled"); run.finished_at = datetime.now(timezone.utc)
                run.progress = {**(run.progress or {}), "cancelled": True}
                await append_event(task_session, run.id, "run.cancelled", "cancelled", "分析任务已取消")
                await task_session.commit()
        except Exception as exc:
            await task_session.rollback()
            run = await task_session.get(AnalysisRun, run_id)
            if run and run.status=='running':
                transition_run(run, "failed"); run.error = f"{type(exc).__name__}: {str(exc)[:1000]}"; run.finished_at = datetime.now(timezone.utc)
                await append_event(task_session, run.id, "run.failed", "failed", run.error)
                await task_session.commit()
