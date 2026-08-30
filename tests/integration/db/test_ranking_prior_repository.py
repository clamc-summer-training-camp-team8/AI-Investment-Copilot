from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.core.domain import RankingPriorItemRecord, RankingPriorSnapshotRecord
from app.db.repositories.ranking import SqlRankingPriorRepo

pytestmark = pytest.mark.integration


def test_ranking_prior_repository_round_trip(session: Session) -> None:
    suffix = uuid4().hex[:10]
    snapshot_id = f"RPS-{suffix}"
    as_of = datetime(2025, 12, 31, tzinfo=UTC)
    repo = SqlRankingPriorRepo(session)
    repo.add_snapshot(
        RankingPriorSnapshotRecord(
            snapshot_id=snapshot_id,
            security_id=f"SEC-{suffix}",
            direction="看多",
            horizon="12M",
            as_of=as_of,
            ranker_version="thesis-prior-v1",
            feature_version="prior-features-v1",
            status="provisional",
        )
    )
    repo.add_items(
        [
            RankingPriorItemRecord(
                snapshot_id=snapshot_id,
                object_type="document_segment",
                object_id=f"DOC-{suffix}#paragraph-1",
                base_rank=1,
                base_score=Decimal("0.8"),
                final_rank=1,
                final_score=Decimal("0.86"),
                feature_scores={"source_authority": 1.0},
                reason_codes=["AUTHORITATIVE_SOURCE"],
                citation_locators=[f"DOC-{suffix}#paragraph-1"],
            )
        ]
    )
    active = repo.active_snapshot(
        security_id=f"SEC-{suffix}", direction="看多", horizon="12M", as_of=as_of
    )
    items = repo.items_for_objects(
        snapshot_id,
        object_type="document_segment",
        object_ids=(f"DOC-{suffix}#paragraph-1",),
    )
    assert active is not None and active.snapshot_id == snapshot_id
    assert len(items) == 1
    assert items[0].final_score == Decimal("0.86000000")
