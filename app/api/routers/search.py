"""全局搜索路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import ActorDep, SettingsDep, UowDep
from app.schemas.search import (
    GlobalSearchGroupOut,
    GlobalSearchItemOut,
    GlobalSearchOut,
    SearchTargetOut,
)
from app.services import global_search
from app.services.errors import ValidationFailed

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=GlobalSearchOut)
def search_all(
    actor: ActorDep,
    conf: SettingsDep,
    uow: UowDep,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    types: Annotated[str, Query(max_length=100)] = "security,industry,thesis,event,document",
    limit_per_type: Annotated[int, Query(ge=1, le=10)] = 5,
) -> GlobalSearchOut:
    if not conf.global_search_enabled:
        raise HTTPException(
            status_code=404,
            detail={"code": "GLOBAL_SEARCH_DISABLED", "message": "全局搜索当前未启用"},
        )
    try:
        result = global_search.search(
            uow,
            query=q,
            actor=actor,
            settings=conf,
            types=tuple(item.strip() for item in types.split(",") if item.strip()),
            limit_per_type=limit_per_type,
        )
    except ValidationFailed as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "SEARCH_QUERY_INVALID", "message": str(exc)},
        ) from exc
    return GlobalSearchOut(
        query=result.query,
        request_id=result.request_id,
        groups=[
            GlobalSearchGroupOut(
                type=group.type,
                items=[
                    GlobalSearchItemOut(
                        id=item.id,
                        title=item.title,
                        subtitle=item.subtitle,
                        excerpt=item.excerpt,
                        match_kind=item.match_kind,
                        target=SearchTargetOut(kind=item.target.kind, id=item.target.id),
                        content_status=item.content_status,
                        content_kind=item.content_kind,
                        retrieval_mode=item.retrieval_mode,
                        published_at=item.published_at,
                    )
                    for item in group.items
                ],
            )
            for group in result.groups
        ],
    )
