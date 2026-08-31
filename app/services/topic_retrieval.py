from __future__ import annotations

from datetime import datetime

from app.core.domain import UnitOfWork
from app.services.errors import ValidationFailed


def ranked_topic_context(
    uow: UnitOfWork,
    *,
    security_id: str,
    direction: str,
    horizon: str,
    as_of: datetime | None,
    limit: int = 3,
) -> tuple[str | None, list[dict[str, object]]]:
    if limit < 1 or limit > 10:
        raise ValidationFailed("主题返回数量必须位于 1 到 10")
    snapshot = uow.ranking.active_snapshot(
        security_id=security_id, direction=direction, horizon=horizon, as_of=as_of
    )
    topics = {
        row.topic_id: row
        for row in uow.ranking.topics(security_id=security_id, direction=direction, horizon=horizon)
    }
    if snapshot is None:
        return None, []
    ranked = uow.ranking.ranked_items(snapshot.snapshot_id, object_type="logic_topic", limit=limit)
    result: list[dict[str, object]] = []
    for item in ranked:
        topic = topics.get(item.object_id)
        if topic is None:
            continue
        relations = uow.ranking.topic_relations(topic.topic_id)
        grouped: dict[str, list[dict[str, object]]] = {}
        for relation in relations:
            grouped.setdefault(relation.object_type, []).append(
                {
                    "object_id": relation.object_id,
                    "relation": relation.relation,
                    "confidence": float(relation.confidence),
                    "reason": relation.reason,
                    "citation_locators": relation.citation_locators,
                }
            )
        result.append(
            {
                "topic_id": topic.topic_id,
                "name": topic.name,
                "normalized_statement": topic.normalized_statement,
                "direction": topic.direction,
                "horizon": topic.horizon,
                "rank": item.final_rank,
                "score": float(item.final_score),
                "base_score": float(item.base_score),
                "feature_scores": item.feature_scores,
                "reason_codes": item.reason_codes,
                "primary_eligible": (
                    "PRIMARY_TOPIC_ELIGIBLE" in item.reason_codes
                    and "MODEL_PRIMARY_REJECTED" not in item.reason_codes
                ),
                "citation_locators": item.citation_locators,
                "relations": grouped,
                "metadata": topic.metadata,
            }
        )
    return snapshot.snapshot_id, result
