from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.ranking.builder import PriorInput, build_snapshot
from app.ranking.features import PriorFeatures, evidence_prior
from tests.fakes import build_fake_uow


def test_build_snapshot_is_stable_and_provisional() -> None:
    uow = build_fake_uow()
    kwargs = {
        "security_id": "600276.SH",
        "direction": "看多",
        "horizon": "12M",
        "as_of": datetime(2025, 12, 31, tzinfo=UTC),
        "ranker_version": "thesis-prior-v1",
        "feature_version": "prior-features-v1",
        "inputs": [
            PriorInput(
                object_type="document_segment",
                object_id="DOC-1#paragraph-1",
                features=PriorFeatures(source_authority=1.0, direct_relevance=1.0),
                citation_locators=("DOC-1#paragraph-1",),
            )
        ],
    }
    first = build_snapshot(uow, **kwargs)
    second = build_snapshot(uow, **kwargs)
    assert first.snapshot_id == second.snapshot_id
    assert second.status == "provisional"
    assert len(uow.ranking.snapshots) == 1
    assert len(uow.ranking.items) == 1


def test_build_snapshot_rejects_naive_as_of() -> None:
    with pytest.raises(ValueError, match="时区"):
        build_snapshot(
            build_fake_uow(),
            security_id="600276.SH",
            direction="看多",
            horizon="12M",
            as_of=datetime(2025, 12, 31),
            ranker_version="v1",
            feature_version="v1",
            inputs=[],
        )


def test_low_value_penalty_reduces_prior_score() -> None:
    normal = evidence_prior(PriorFeatures())
    low_value = evidence_prior(PriorFeatures(low_value_penalty=1.0))

    assert low_value == pytest.approx(normal - 0.35)
