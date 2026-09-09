from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_session
from .models import AuditLog, Report, ReportComment, ReportWorkflow, ShareLink, User, Workspace, WorkspaceMember
from .schemas import (
    AuditLogOut, ReportCommentCreate, ReportCommentOut, ReportOut, ReportWorkflowOut,
    ShareLinkCreate, ShareLinkOut, TeamContextOut, TeamMemberCreate, TeamMemberOut, TeamMemberUpdate,
)


router = APIRouter(prefix="/api/v1", tags=["team"])

ROLE_PERMISSIONS = {
    "owner": ["workspace.manage", "member.manage", "data.edit", "analysis.view", "analysis.execute", "code.view", "template.manage", "template.use", "report.view", "report.edit", "report.review", "report.publish", "audit.view"],
    "admin": ["member.manage", "data.edit", "analysis.view", "analysis.execute", "code.view", "template.manage", "template.use", "report.view", "report.edit", "report.review", "report.publish", "audit.view"],
    "analyst": ["data.edit", "analysis.view", "analysis.execute", "code.view", "template.use", "report.view", "report.edit", "report.review"],
    "viewer": ["analysis.view", "report.view"],
}


async def ensure_owner(session: AsyncSession, workspace_id: str) -> tuple[User, WorkspaceMember]:
    workspace = await session.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(404, "工作区不存在")
    member = await session.scalar(
        select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.role == "owner")
    )
    if member:
        return await session.get(User, member.user_id), member
    user = await session.scalar(select(User).where(User.email == "owner@local.insight"))
    if not user:
        user = User(email="owner@local.insight", display_name="本机所有者")
        session.add(user)
        await session.flush()
    member = WorkspaceMember(workspace_id=workspace_id, user_id=user.id, role="owner")
    session.add(member)
    await session.commit()
    await session.refresh(member)
    return user, member


async def actor_for(session: AsyncSession, workspace_id: str, actor_id: str | None) -> tuple[User, WorkspaceMember]:
    await ensure_owner(session, workspace_id)
    member = None
    if actor_id:
        member = await session.scalar(select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == actor_id,
        ))
        if not member:
            raise HTTPException(403, "当前身份不是该工作区成员")
    else:
        member = await session.scalar(select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.role == "owner",
        ))
    user = await session.get(User, member.user_id)
    if not user or not user.active:
        raise HTTPException(403, "成员已停用")
    return user, member


def require(member: WorkspaceMember, permission: str) -> None:
    if permission not in ROLE_PERMISSIONS.get(member.role, []):
        raise HTTPException(403, f"当前角色无权执行：{permission}")


async def audit(session: AsyncSession, workspace_id: str, actor_id: str | None, action: str, resource_type: str, resource_id: str | None, detail: dict | None = None) -> None:
    session.add(AuditLog(workspace_id=workspace_id, actor_id=actor_id, action=action, resource_type=resource_type, resource_id=resource_id, detail=detail or {}))


def member_out(member: WorkspaceMember, user: User) -> TeamMemberOut:
    return TeamMemberOut(id=member.id, user_id=user.id, email=user.email, display_name=user.display_name, role=member.role, created_at=member.created_at)


@router.get("/team/context", response_model=TeamContextOut)
async def team_context(workspace_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    actor, membership = await actor_for(session, workspace_id, x_actor_id)
    members = (await session.scalars(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id).order_by(WorkspaceMember.created_at))).all()
    users = {item.id: item for item in (await session.scalars(select(User).where(User.id.in_([m.user_id for m in members])))).all()}
    return TeamContextOut(current_user_id=actor.id, current_role=membership.role, members=[member_out(m, users[m.user_id]) for m in members], permissions=ROLE_PERMISSIONS[membership.role])


@router.post("/team/members", response_model=TeamMemberOut, status_code=201)
async def add_member(payload: TeamMemberCreate, workspace_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    actor, membership = await actor_for(session, workspace_id, x_actor_id); require(membership, "member.manage")
    email = payload.email.strip().lower()
    user = await session.scalar(select(User).where(User.email == email))
    if not user:
        user = User(email=email, display_name=payload.display_name.strip()); session.add(user); await session.flush()
    existing = await session.scalar(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user.id))
    if existing:
        raise HTTPException(409, "该成员已在工作区")
    item = WorkspaceMember(workspace_id=workspace_id, user_id=user.id, role=payload.role, invited_by=actor.id)
    session.add(item); await session.flush(); await audit(session, workspace_id, actor.id, "member.invite", "member", user.id, {"role": payload.role}); await session.commit(); await session.refresh(item)
    return member_out(item, user)


@router.patch("/team/members/{member_id}", response_model=TeamMemberOut)
async def update_member(member_id: str, payload: TeamMemberUpdate, workspace_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    actor, membership = await actor_for(session, workspace_id, x_actor_id); require(membership, "member.manage")
    item = await session.get(WorkspaceMember, member_id)
    if not item or item.workspace_id != workspace_id: raise HTTPException(404, "成员不存在")
    if item.role == "owner": raise HTTPException(409, "不能修改所有者角色")
    item.role = payload.role; user = await session.get(User, item.user_id)
    await audit(session, workspace_id, actor.id, "member.role_change", "member", user.id, {"role": payload.role}); await session.commit(); await session.refresh(item)
    return member_out(item, user)


@router.delete("/team/members/{member_id}", status_code=204)
async def remove_member(member_id: str, workspace_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    actor, membership = await actor_for(session, workspace_id, x_actor_id); require(membership, "member.manage")
    item = await session.get(WorkspaceMember, member_id)
    if not item or item.workspace_id != workspace_id: raise HTTPException(404, "成员不存在")
    if item.role == "owner": raise HTTPException(409, "不能移除所有者")
    await audit(session, workspace_id, actor.id, "member.remove", "member", item.user_id); await session.delete(item); await session.commit()


async def report_and_actor(report_id: str, actor_id: str | None, session: AsyncSession, permission: str, allow_deleted: bool = False):
    report = await session.get(Report, report_id)
    if not report: raise HTTPException(404, "报告不存在")
    actor, membership = await actor_for(session, report.workspace_id, actor_id); require(membership, permission)
    if report.deleted_at and not allow_deleted: raise HTTPException(410, "报告已在回收站，请先恢复")
    return report, actor, membership


async def workflow_for(session: AsyncSession, report_id: str) -> ReportWorkflow:
    item = await session.get(ReportWorkflow, report_id)
    if not item:
        item = ReportWorkflow(report_id=report_id, status="draft"); session.add(item); await session.flush()
    return item


@router.get("/reports/{report_id}/workflow", response_model=ReportWorkflowOut)
async def get_workflow(report_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    report, _, _ = await report_and_actor(report_id, x_actor_id, session, "report.view")
    item = await workflow_for(session, report.id); await session.commit(); await session.refresh(item); return item


@router.post("/reports/{report_id}/workflow/{action}", response_model=ReportWorkflowOut)
async def transition_report(report_id: str, action: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    permission = "report.publish" if action in {"approve", "publish"} else "report.review"
    report, actor, _ = await report_and_actor(report_id, x_actor_id, session, permission)
    item = await workflow_for(session, report.id)
    transitions = {"submit": ({"draft", "approved"}, "in_review"), "approve": ({"in_review"}, "approved"), "publish": ({"approved"}, "published"), "return": ({"in_review", "approved"}, "draft")}
    if action not in transitions: raise HTTPException(404, "未知审核动作")
    allowed, target = transitions[action]
    if item.status not in allowed: raise HTTPException(409, f"当前状态 {item.status} 不能执行 {action}")
    item.status = target
    if action == "submit": item.submitted_by = actor.id
    if action == "approve": item.approved_by = actor.id
    if action == "publish": item.published_by = actor.id
    await audit(session, report.workspace_id, actor.id, f"report.{action}", "report", report.id, {"status": target}); await session.commit(); await session.refresh(item); return item


@router.get("/reports/{report_id}/comments", response_model=list[ReportCommentOut])
async def list_comments(report_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    await report_and_actor(report_id, x_actor_id, session, "report.view")
    items = (await session.scalars(select(ReportComment).where(ReportComment.report_id == report_id).order_by(ReportComment.created_at))).all()
    users = {u.id: u for u in (await session.scalars(select(User).where(User.id.in_([i.author_id for i in items])))).all()} if items else {}
    return [ReportCommentOut(id=i.id, report_id=i.report_id, author_id=i.author_id, author_name=users[i.author_id].display_name, block_id=i.block_id, body=i.body, resolved=i.resolved, created_at=i.created_at) for i in items]


@router.post("/reports/{report_id}/comments", response_model=ReportCommentOut, status_code=201)
async def add_comment(report_id: str, payload: ReportCommentCreate, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    report, actor, _ = await report_and_actor(report_id, x_actor_id, session, "report.review")
    item = ReportComment(report_id=report_id, author_id=actor.id, block_id=payload.block_id, body=payload.body.strip()); session.add(item); await session.flush()
    await audit(session, report.workspace_id, actor.id, "comment.create", "report", report_id, {"block_id": payload.block_id}); await session.commit(); await session.refresh(item)
    return ReportCommentOut(id=item.id, report_id=report_id, author_id=actor.id, author_name=actor.display_name, block_id=item.block_id, body=item.body, resolved=False, created_at=item.created_at)


@router.patch("/reports/{report_id}/comments/{comment_id}/resolve", response_model=ReportCommentOut)
async def resolve_comment(report_id: str, comment_id: str, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    report, actor, _ = await report_and_actor(report_id, x_actor_id, session, "report.review")
    item = await session.get(ReportComment, comment_id)
    if not item or item.report_id != report_id: raise HTTPException(404, "批注不存在")
    item.resolved = True; author = await session.get(User, item.author_id)
    await audit(session, report.workspace_id, actor.id, "comment.resolve", "report", report_id, {"comment_id": comment_id}); await session.commit(); await session.refresh(item)
    return ReportCommentOut(id=item.id, report_id=report_id, author_id=item.author_id, author_name=author.display_name, block_id=item.block_id, body=item.body, resolved=True, created_at=item.created_at)


@router.post("/reports/{report_id}/share", response_model=ShareLinkOut, status_code=201)
async def create_share(report_id: str, payload: ShareLinkCreate, request: Request, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    report, actor, _ = await report_and_actor(report_id, x_actor_id, session, "report.publish")
    workflow = await workflow_for(session, report_id)
    if workflow.status != "published": raise HTTPException(409, "只有已发布报告可以创建分享链接")
    token = secrets.token_urlsafe(32); expires = datetime.now(timezone.utc) + timedelta(hours=payload.expires_in_hours)
    item = ShareLink(report_id=report_id, token_hash=hashlib.sha256(token.encode()).hexdigest(), created_by=actor.id, expires_at=expires); session.add(item); await session.flush()
    await audit(session, report.workspace_id, actor.id, "share.create", "report", report_id, {"expires_at": expires.isoformat()}); await session.commit(); await session.refresh(item)
    url = str(request.base_url).rstrip("/") + f"/shared/{token}"
    return ShareLinkOut(id=item.id, report_id=report_id, url=url, expires_at=expires, revoked=False)


@router.get("/shared/reports/{token}", response_model=ReportOut)
async def shared_report(token: str, session: AsyncSession = Depends(get_session)):
    item = await session.scalar(select(ShareLink).where(ShareLink.token_hash == hashlib.sha256(token.encode()).hexdigest()))
    now = datetime.now(timezone.utc)
    if not item or item.revoked or (item.expires_at and item.expires_at.replace(tzinfo=timezone.utc) <= now): raise HTTPException(404, "分享链接无效或已过期")
    report = await session.get(Report, item.report_id)
    if not report or report.deleted_at: raise HTTPException(404, "报告已不可用")
    return ReportOut(id=report.id, workspace_id=report.workspace_id, dataset_id=report.dataset_id, title=report.title, document=report.document, created_at=report.created_at, updated_at=report.updated_at)


@router.get("/audit", response_model=list[AuditLogOut])
async def list_audit(workspace_id: str, limit: int = 100, x_actor_id: str | None = Header(default=None), session: AsyncSession = Depends(get_session)):
    _, membership = await actor_for(session, workspace_id, x_actor_id); require(membership, "audit.view")
    rows = (await session.scalars(select(AuditLog).where(AuditLog.workspace_id == workspace_id).order_by(AuditLog.created_at.desc()).limit(min(limit, 500)))).all()
    ids = [r.actor_id for r in rows if r.actor_id]; users = {u.id: u for u in (await session.scalars(select(User).where(User.id.in_(ids)))).all()} if ids else {}
    return [AuditLogOut(id=r.id, actor_id=r.actor_id, actor_name=users.get(r.actor_id).display_name if r.actor_id in users else "系统", action=r.action, resource_type=r.resource_type, resource_id=r.resource_id, detail=r.detail or {}, created_at=r.created_at) for r in rows]
