"""变化雷达只读接口：按明确逻辑上下文返回可读证据列表。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import ActorDep, UowDep
from app.api.feed_presenter import to_feed_item
from app.core.enums import ConfirmationStatus, ImpactDirection
from app.schemas.thesis import EvidenceFeedPage, PageMeta
from app.services import permission, query as query_service
from app.services.errors import NotVisible

router = APIRouter(tags=["radar"])


@router.get("/radar/evidence", response_model=EvidenceFeedPage)
def list_radar_evidence(
    thesis_id: Annotated[str, Query(min_length=1)],
    actor: ActorDep,
    uow: UowDep,
    status: Annotated[list[str] | None, Query()] = None,
    direction: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=query_service.MAX_LIMIT)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EvidenceFeedPage:
    thesis = uow.thesis.get(thesis_id)
    if thesis is None:
        raise HTTPException(status_code=404, detail="逻辑不存在或无访问权限")
    try:
        permission.ensure_thesis_visible(
            actor, thesis_id=thesis_id, owner=thesis.owner,
            visibility=thesis.visibility, team=thesis.team,
        )
    except NotVisible as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        statuses = tuple(ConfirmationStatus(item) for item in (status or []))
        parsed_direction = ImpactDirection(direction) if direction else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="状态或方向筛选值不合法") from exc

    records, total = uow.feed.search(
        thesis_ids=(thesis_id,), statuses=statuses, direction=parsed_direction,
        limit=limit, offset=offset,
    )
    return EvidenceFeedPage(
        items=[to_feed_item(item, actor_id=actor.user_id) for item in records],
        page=PageMeta(total=total, limit=limit, offset=offset),
    )
