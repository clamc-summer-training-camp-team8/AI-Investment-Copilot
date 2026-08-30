from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.core.config import Settings
from app.core.domain import (
    AssetSearchHitRecord,
    RankingPriorItemRecord,
    RankingPriorSnapshotRecord,
)
from app.ranking.types import RankingQuery
from app.services import ranked_retrieval
from app.services.permission import Actor
from tests.fakes import build_fake_uow


def test_ranked_search_uses_active_prior_snapshot() -> None:
    uow = build_fake_uow()
    as_of = datetime(2025, 12, 31, tzinfo=UTC)
    uow.ranking.add_snapshot(
        RankingPriorSnapshotRecord(
            snapshot_id="RPS-1",
            security_id="600276.SH",
            direction="看多",
            horizon="12M",
            as_of=as_of,
            ranker_version="v1",
            feature_version="v1",
            status="provisional",
        )
    )
    uow.ranking.add_items(
        [
            RankingPriorItemRecord(
                snapshot_id="RPS-1",
                object_type="document_segment",
                object_id="DOC-1#paragraph-1",
                base_rank=1,
                base_score=Decimal("0.9"),
                final_rank=1,
                final_score=Decimal("0.9"),
            )
        ]
    )
    uow.assets.hybrid_search_segments = lambda **kwargs: [  # type: ignore[method-assign]
        AssetSearchHitRecord(
            "DOC-1",
            "DOC-1#paragraph-1",
            "创新药收入增长",
            "公开",
            1.0,
            "hybrid",
            0.8,
            0.9,
        )
    ]
    snapshot_id, items = ranked_retrieval.search(
        uow,
        query=RankingQuery(
            text="创新药收入",
            security_ids=("600276.SH",),
            as_of=as_of,
            profile="primary_context",
        ),
        actor=Actor(user_id="researcher"),
        settings=Settings(_env_file=None),
    )
    assert snapshot_id == "RPS-1"
    assert items[0].prior_score == 0.9
    assert items[0].graph_score is None
