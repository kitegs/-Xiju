"""Bounded report summaries; legacy full-document endpoints remain compatible."""
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_session
from .models import Report
from .team import actor_for, require

router = APIRouter(prefix="/api/v1/report-catalog", tags=["report-catalog"])


@router.get("")
async def report_catalog(
    workspace_id: str, deleted: bool = False, q: str = Query("", max_length=255),
    dataset_id: str | None = None, offset: int = Query(0, ge=0), limit: int = Query(24, ge=1, le=100),
    sort: Literal["updated_desc", "created_desc", "title_asc", "charts_desc"] = "updated_desc",
    x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session),
):
    _, membership = await actor_for(session, workspace_id, x_actor_id)
    require(membership, "report.view")
    conditions = [Report.workspace_id == workspace_id,
                  Report.deleted_at.is_not(None) if deleted else Report.deleted_at.is_(None)]
    if q.strip():
        conditions.append(Report.title.contains(q.strip(), autoescape=True))
    if dataset_id:
        conditions.append(Report.dataset_id == dataset_id)
    chart_count = func.coalesce(func.json_array_length(Report.document["charts"]), 0)
    ordering = {"updated_desc": Report.updated_at.desc(), "created_desc": Report.created_at.desc(),
                "title_asc": Report.title.asc(), "charts_desc": chart_count.desc()}[sort]
    # Project only metadata in SQL: never deserialize full evidence/chart arrays
    # just to render a report card. This endpoint targets the local SQLite mode.
    query = select(Report.id, Report.title, Report.dataset_id, Report.project_id,
                   Report.created_at, Report.updated_at, Report.deleted_at,
                   func.substr(Report.document["summary"].as_string(), 1, 300).label("summary"),
                   chart_count.label("chart_count")).where(*conditions)
    total = await session.scalar(select(func.count()).select_from(Report).where(*conditions))
    rows = (await session.execute(query.order_by(ordering, Report.id).offset(offset).limit(limit))).mappings().all()
    return {"items": [dict(row) for row in rows], "total": total, "offset": offset, "limit": limit,
            "has_more": offset + len(rows) < total}
