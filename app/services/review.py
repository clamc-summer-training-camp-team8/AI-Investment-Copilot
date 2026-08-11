"""Researcher review-task workflow and its human-only resolution gate."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from app.core.domain import ReviewTaskRecord, UnitOfWork
from app.core.timeutil import now
from app.services import audit, permission
from app.services.errors import NotVisible, ValidationFailed
from app.services.permission import Actor

VALID_TRIGGERS = {"到期", "重大事件", "失效条件", "人工发起", "低置信", "处理失败"}
VALID_PRIORITIES = {"低", "普通", "高", "紧急"}
PENDING = "待处理"
RESOLVED = "已完成"


def create_task(
    uow: UnitOfWork,
    *,
    thesis_id: str,
    trigger: str,
    priority: str,
    assignee: str,
    actor: Actor,
    detail: dict[str, object] | None = None,
) -> ReviewTaskRecord:
    thesis = uow.thesis.get(thesis_id)
    if thesis is None:
        raise NotVisible("逻辑不存在或无访问权限")
    permission.ensure_thesis_visible(
        actor,
        thesis_id=thesis_id,
        owner=thesis.owner,
        visibility=thesis.visibility,
        team=thesis.team,
    )
    if trigger not in VALID_TRIGGERS:
        raise ValidationFailed(f"未知复核触发类型: {trigger}")
    if priority not in VALID_PRIORITIES:
        raise ValidationFailed(f"未知复核优先级: {priority}")
    if not assignee.strip():
        raise ValidationFailed("复核任务必须指定处理人")

    task = ReviewTaskRecord(
        task_id=f"RVW-{uuid4().hex}",
        thesis_id=thesis_id,
        trigger=trigger,
        priority=priority,
        assignee=assignee,
        detail=detail,
    )
    saved = uow.reviews.add(task)
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action=audit.CREATE,
        object_type="review_task",
        object_id=saved.task_id,
        detail={"thesis_id": thesis_id, "trigger": trigger, "assignee": assignee},
    )
    return saved


def list_assigned(
    uow: UnitOfWork, *, actor: Actor, state: str | None = None, limit: int = 100
) -> list[ReviewTaskRecord]:
    return uow.reviews.list_for_assignee(actor.user_id, state=state, limit=limit)


def get_assigned(uow: UnitOfWork, *, task_id: str, actor: Actor) -> ReviewTaskRecord:
    task = uow.reviews.get(task_id)
    if task is None or task.assignee != actor.user_id:
        raise NotVisible("复核任务不存在或无访问权限")
    return task


def resolve(
    uow: UnitOfWork,
    *,
    task_id: str,
    actor: Actor,
    resolution: str,
) -> ReviewTaskRecord:
    task = get_assigned(uow, task_id=task_id, actor=actor)
    if task.state != PENDING:
        raise ValidationFailed("复核任务已经完成，不能重复处置")
    if len(resolution.strip()) < 2:
        raise ValidationFailed("复核结论不能为空")
    updated = replace(
        task,
        state=RESOLVED,
        resolution=resolution.strip(),
        resolved_at=now(),
    )
    uow.reviews.update(updated)
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action=audit.CONFIRM,
        object_type="review_task",
        object_id=task_id,
        detail={"resolution": resolution.strip(), "thesis_id": task.thesis_id},
    )
    return updated
