from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import LlmUsageLog
from .schemas import TokenUsageGroup, TokenUsageItem, TokenUsageSummary, TokenUsageTotals


UsageRange = Literal["today", "7d", "all"]
UsageGroup = Literal["stage", "model", "run", "report", "dashboard"]
GROUP_FIELDS = {
    "stage": "stage",
    "model": "model",
    "run": "run_id",
    "report": "report_id",
    "dashboard": "dashboard_id",
}
TOKEN_FIELDS = ("prompt_tokens", "cache_hit_tokens", "cache_miss_tokens", "completion_tokens", "total_tokens")


def _range_start(value: UsageRange, now: datetime) -> datetime | None:
    if value == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if value == "7d":
        return now - timedelta(days=7)
    return None


def _totals(rows: list[LlmUsageLog]) -> TokenUsageTotals:
    values = {field: sum(int(getattr(row, field) or 0) for row in rows) for field in TOKEN_FIELDS}
    return TokenUsageTotals(**values, call_count=len(rows))


def _item(row: LlmUsageLog) -> TokenUsageItem:
    return TokenUsageItem(
        id=row.id, conversation_id=row.conversation_id, plan_id=row.plan_id,
        run_id=row.run_id, report_id=row.report_id, dashboard_id=row.dashboard_id,
        stage=row.stage or "unknown", purpose=row.purpose or "", provider=row.provider,
        model=row.model, request_id=row.request_id or "", latency_ms=row.latency_ms or 0,
        status=row.status, usage_unavailable=bool(row.usage_unavailable), created_at=row.created_at,
        **_totals([row]).model_dump(),
    )


async def summarize_token_usage(
    session: AsyncSession,
    workspace_id: str,
    usage_range: UsageRange = "7d",
    group_by: UsageGroup = "stage",
    *,
    run_id: str | None = None,
    report_id: str | None = None,
) -> TokenUsageSummary:
    query = select(LlmUsageLog).where(LlmUsageLog.workspace_id == workspace_id)
    start = _range_start(usage_range, datetime.now(timezone.utc))
    if start is not None:
        query = query.where(LlmUsageLog.created_at >= start)
    if run_id is not None:
        query = query.where(LlmUsageLog.run_id == run_id)
    if report_id is not None:
        query = query.where(LlmUsageLog.report_id == report_id)
    rows = list((await session.scalars(query.order_by(LlmUsageLog.created_at.desc()))).all())
    grouped: dict[str, list[LlmUsageLog]] = {}
    field = GROUP_FIELDS[group_by]
    for row in rows:
        grouped.setdefault(str(getattr(row, field) or "未关联"), []).append(row)
    groups = [TokenUsageGroup(key=key, **_totals(items).model_dump()) for key, items in grouped.items()]
    groups.sort(key=lambda item: (-item.total_tokens, item.key))
    return TokenUsageSummary(
        workspace_id=workspace_id, range=usage_range, group_by=group_by,
        totals=_totals(rows), groups=groups,
        unavailable_call_count=sum(bool(row.usage_unavailable) for row in rows),
        latest=[_item(row) for row in rows[:50]],
    )
