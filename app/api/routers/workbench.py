"""工作台路由（PRD 6.1 一级导航之一）。

只读。回答「我今天该处理什么」：状态概览、待确认证据、待处置状态建议、到期复核。

所有条目都经过可见性过滤，因此不同用户看到的待办不同。这不是性能优化的余地问题——
把别人的待办显示给我，等于泄露他人的研究覆盖范围（PRD 12.1）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ActorDep, UowDep
from app.api.feed_presenter import to_feed_item
from app.core.domain import ThesisQuery
from app.core.enums import ConfirmationStatus
from app.schemas.thesis import EvidenceFeedPage, PageMeta, PendingItemOut, WorkbenchOut
from app.services import query as query_service
from app.services.permission import can_view_thesis

router = APIRouter(tags=["workbench"])


def _to_items(items: list[query_service.PendingItem]) -> list[PendingItemOut]:
    return [
        PendingItemOut(
            kind=i.kind,
            thesis_id=i.thesis_id,
            title=i.title,
            object_id=i.object_id,
            summary=i.summary,
            occurred_on=i.occurred_on,
        )
        for i in items
    ]


@router.get("/workbench", response_model=WorkbenchOut)
def get_workbench(
    actor: ActorDep,
    uow: UowDep,
    limit: Annotated[int, Query(ge=1, le=query_service.MAX_LIMIT)] = 20,
) -> WorkbenchOut:
    """工作台聚合。每类待办各取前 limit 条。"""
    view = query_service.workbench(uow, actor, limit=limit)
    return WorkbenchOut(
        status_counts=view.status_counts,
        pending_evidence=_to_items(view.pending_evidence),
        pending_suggestions=_to_items(view.pending_suggestions),
        review_due=_to_items(view.review_due),
    )


@router.get("/workbench/tasks", response_model=EvidenceFeedPage)
def get_readable_evidence_tasks(
    actor: ActorDep,
    uow: UowDep,
    priority: Annotated[list[str] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=query_service.MAX_LIMIT)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EvidenceFeedPage:
    """返回可读的待确认证据任务，作为工作台主任务列表。"""
    priorities = tuple(priority or ())
    if any(item not in {"high", "medium", "low"} for item in priorities):
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="优先级必须是 high、medium 或 low")
    candidates, _ = uow.thesis.search(ThesisQuery(limit=query_service.MAX_LIMIT))
    visible_ids = tuple(
        item.thesis_id
        for item in candidates
        if can_view_thesis(actor, owner=item.owner, visibility=item.visibility, team=item.team)
    )
    records, total = uow.feed.search(
        thesis_ids=visible_ids,
        statuses=(ConfirmationStatus.PENDING,),
        priorities=priorities,
        limit=limit,
        offset=offset,
    )
    return EvidenceFeedPage(
        items=[to_feed_item(item, actor_id=actor.user_id) for item in records],
        page=PageMeta(total=total, limit=limit, offset=offset),
    )
