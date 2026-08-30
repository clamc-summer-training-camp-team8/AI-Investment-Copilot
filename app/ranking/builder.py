from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256

from app.core.domain import (
    RankingPriorItemRecord,
    RankingPriorSnapshotRecord,
    UnitOfWork,
)
from app.ranking.features import PriorFeatures, score_for_object


@dataclass(frozen=True)
class PriorInput:
    object_type: str
    object_id: str
    features: PriorFeatures
    reason_codes: tuple[str, ...] = ()
    citation_locators: tuple[str, ...] = ()
    judge_score: float | None = None
    judge_confidence: float | None = None
    content: str = ""


def _snapshot_id(security_id: str, direction: str, horizon: str, as_of: datetime, version: str):
    raw = f"{security_id}|{direction}|{horizon}|{as_of.isoformat()}|{version}"
    return f"RPS-{sha256(raw.encode()).hexdigest()[:24]}"


def build_snapshot(
    uow: UnitOfWork,
    *,
    security_id: str,
    direction: str,
    horizon: str,
    as_of: datetime,
    ranker_version: str,
    feature_version: str,
    inputs: list[PriorInput],
    judge_model_version: str | None = None,
    prompt_version: str | None = None,
    judge_weight: float = 0.3,
) -> RankingPriorSnapshotRecord:
    if as_of.tzinfo is None:
        raise ValueError("as_of 必须包含时区")
    snapshot_id = _snapshot_id(security_id, direction, horizon, as_of, ranker_version)
    existing = uow.ranking.get_snapshot(snapshot_id)
    if existing is None:
        snapshot = RankingPriorSnapshotRecord(
            snapshot_id=snapshot_id,
            security_id=security_id,
            direction=direction,
            horizon=horizon,
            as_of=as_of,
            ranker_version=ranker_version,
            feature_version=feature_version,
            judge_model_version=judge_model_version,
            prompt_version=prompt_version,
            status="generated",
            metadata={"input_count": len(inputs)},
        )
        uow.ranking.add_snapshot(snapshot)
    else:
        snapshot = existing
    scored = []
    for row in inputs:
        base_score = score_for_object(row.object_type, row.features)
        final_score = (
            (1 - judge_weight) * base_score + judge_weight * row.judge_score
            if row.judge_score is not None
            else base_score
        )
        scored.append((row, base_score, round(final_score, 8)))
    scored.sort(
        key=lambda value: (
            value[0].object_type,
            1
            if value[0].object_type == "logic_topic"
            and (
                "PRIMARY_TOPIC_ELIGIBLE" not in value[0].reason_codes
                or "MODEL_PRIMARY_REJECTED" in value[0].reason_codes
            )
            else 0,
            -value[2],
            value[0].object_id,
        )
    )
    ranks: dict[str, int] = {}
    records = []
    for row, base_score, final_score in scored:
        ranks[row.object_type] = ranks.get(row.object_type, 0) + 1
        object_rank = ranks[row.object_type]
        records.append(
            RankingPriorItemRecord(
                snapshot_id=snapshot_id,
                object_type=row.object_type,
                object_id=row.object_id,
                base_rank=object_rank,
                base_score=Decimal(str(base_score)),
                judge_rank=object_rank if row.judge_score is not None else None,
                judge_score=(
                    Decimal(str(row.judge_score)) if row.judge_score is not None else None
                ),
                judge_confidence=(
                    Decimal(str(row.judge_confidence)) if row.judge_confidence is not None else None
                ),
                final_rank=object_rank,
                final_score=Decimal(str(final_score)),
                feature_scores=row.features.as_dict(),
                reason_codes=list(row.reason_codes),
                citation_locators=list(row.citation_locators),
            )
        )
    uow.ranking.add_items(records)
    uow.ranking.update_snapshot_status(snapshot_id, "provisional")
    return RankingPriorSnapshotRecord(**{**snapshot.__dict__, "status": "provisional"})
