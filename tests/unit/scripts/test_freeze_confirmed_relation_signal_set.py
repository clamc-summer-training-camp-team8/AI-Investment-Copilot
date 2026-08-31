from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from app.core.domain import QuantMarketDatasetRecord
from scripts.freeze_confirmed_relation_signal_set import (
    ConfirmedRelationSignalSource,
    plan_confirmed_signal_set,
)
from tests.fakes import build_fake_uow


def _source(relation_id: str, security_id: str, reviewed_at: datetime):
    return ConfirmedRelationSignalSource(
        relation_id=relation_id,
        evidence_id=f"EVD-{relation_id}",
        security_id=security_id,
        disclosed_at=datetime(2026, 8, 7, tzinfo=UTC),
        reviewed_at=reviewed_at,
        direction="支持",
        strength="中",
    )


def _uow(coverage_end: date):
    uow = build_fake_uow()
    uow.quant.add_market_dataset(
        QuantMarketDatasetRecord(
            dataset_id="MDS-v4",
            data_version="v4",
            manifest_path="real_data/quant/v4/manifest.json",
            manifest_sha256="a" * 64,
            source_policy_id="policy-v1",
            authorization_status="verified",
            adjustment="qfq",
            coverage_start=date(2025, 1, 1),
            coverage_end=coverage_end,
            securities=["600276", "688981", "002594"],
            capabilities={},
            limitations=[],
            status="frozen",
            frozen_by="tester",
            frozen_at=datetime(2026, 9, 1, tzinfo=UTC),
        )
    )
    return uow


def _sources():
    business_tz = timezone(timedelta(hours=8))
    return [
        _source("REL-1", "600276", datetime(2026, 8, 12, 10, tzinfo=business_tz)),
        _source("REL-2", "688981", datetime(2026, 8, 12, 11, tzinfo=business_tz)),
        _source("REL-3", "002594", datetime(2026, 8, 31, 18, 7, tzinfo=business_tz)),
    ]


def test_signal_set_plan_requires_market_data_after_latest_review() -> None:
    with pytest.raises(ValueError, match="数据集只到 2026-08-28"):
        plan_confirmed_signal_set(
            _uow(date(2026, 8, 28)),
            sources=_sources(),
            market_dataset_id="MDS-v4",
            version="confirmed-relations-20260901-v2",
            as_of=datetime(2026, 9, 1, tzinfo=UTC),
            expected_signal_count=3,
            required_relation_ids=frozenset({"REL-3"}),
        )


def test_signal_set_plan_accepts_three_confirmed_securities_with_new_market_coverage() -> None:
    plan = plan_confirmed_signal_set(
        _uow(date(2026, 9, 1)),
        sources=_sources(),
        market_dataset_id="MDS-v4",
        version="confirmed-relations-20260901-v2",
        as_of=datetime(2026, 9, 1, tzinfo=UTC),
        expected_signal_count=3,
        required_relation_ids=frozenset({"REL-3"}),
    )

    assert plan.first_eligible_market_date == "2026-09-01"
    assert [item.security_id for item in plan.signals] == ["600276", "688981", "002594"]
    assert plan.signals[-1].generated_at.isoformat().startswith("2026-08-31T18:07")


def test_signal_set_plan_rejects_missing_required_relation() -> None:
    with pytest.raises(ValueError, match="必要人工确认关系"):
        plan_confirmed_signal_set(
            _uow(date(2026, 9, 1)),
            sources=_sources()[:2],
            market_dataset_id="MDS-v4",
            version="confirmed-relations-20260901-v2",
            as_of=datetime(2026, 9, 1, tzinfo=UTC),
            expected_signal_count=2,
            required_relation_ids=frozenset({"REL-3"}),
        )
