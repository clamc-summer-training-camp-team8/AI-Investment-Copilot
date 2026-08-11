"""工作台路由（PRD 6.1 一级导航之一）。

只读。回答「我今天该处理什么」：状态概览、待确认证据、待处置状态建议、到期复核。

所有条目都经过可见性过滤，因此不同用户看到的待办不同。这不是性能优化的余地问题——
把别人的待办显示给我，等于泄露他人的研究覆盖范围（PRD 12.1）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ActorDep, UowDep
from app.schemas.thesis import PendingItemOut, WorkbenchOut
from app.services import query as query_service

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
