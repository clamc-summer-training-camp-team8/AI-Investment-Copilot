from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import ActorDep, SettingsDep, UowDep
from app.ranking.types import RankingQuery
from app.schemas.ranking import (
    RANKING_PROFILES,
    RankedItemOut,
    RankedSearchIn,
    RankedSearchOut,
    RankedTopicOut,
    TopicContextIn,
    TopicContextOut,
)
from app.services import ranked_retrieval, topic_retrieval
from app.services.errors import ValidationFailed

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


@router.post("/ranked-search", response_model=RankedSearchOut)
def ranked_search(
    payload: RankedSearchIn,
    actor: ActorDep,
    conf: SettingsDep,
    uow: UowDep,
) -> RankedSearchOut:
    if payload.ranking_profile not in RANKING_PROFILES:
        raise HTTPException(status_code=422, detail="未知 ranking_profile")
    if payload.object_types != ["document_segment"]:
        raise HTTPException(status_code=422, detail="V1 仅支持 document_segment")
    try:
        snapshot_id, items = ranked_retrieval.search(
            uow,
            query=RankingQuery(
                text=payload.query,
                security_ids=tuple(payload.security_ids),
                industries=tuple(payload.industries),
                direction=payload.direction,
                horizon=payload.horizon,
                as_of=payload.as_of,
                profile=payload.ranking_profile,
                top_k=payload.top_k,
            ),
            actor=actor,
            settings=conf,
        )
    except (ValidationFailed, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RankedSearchOut(
        embedding_version=conf.embedding_version or "",
        prior_snapshot_id=snapshot_id,
        ranking_profile=payload.ranking_profile,
        items=[RankedItemOut(**item.__dict__) for item in items],
    )


@router.post("/topic-context", response_model=TopicContextOut)
def topic_context(payload: TopicContextIn, actor: ActorDep, uow: UowDep) -> TopicContextOut:
    # Actor dependency intentionally remains mandatory; topic context never bypasses API identity.
    del actor
    try:
        snapshot_id, rows = topic_retrieval.ranked_topic_context(
            uow,
            security_id=payload.security_id,
            direction=payload.direction,
            horizon=payload.horizon,
            as_of=payload.as_of,
            limit=payload.top_k,
        )
    except ValidationFailed as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    topics = [RankedTopicOut(**row) for row in rows]
    primary = next((topic for topic in topics if topic.primary_eligible), None)
    return TopicContextOut(
        prior_snapshot_id=snapshot_id,
        primary_topic=primary,
        alternative_topics=[
            topic for topic in topics if topic.topic_id != (primary.topic_id if primary else None)
        ],
    )
