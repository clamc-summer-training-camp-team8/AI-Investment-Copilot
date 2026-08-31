from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.core.domain import (
    QuantBacktestRecord,
    QuantMarketDatasetRecord,
    QuantSignalSetRecord,
)
from app.core.timeutil import now
from app.db.repositories import build_uow

pytestmark = pytest.mark.integration


def test_冻结行情信号与回测结果可在真实仓储往返(session: Session) -> None:
    suffix = uuid4().hex[:12]
    uow = build_uow(session)
    dataset = QuantMarketDatasetRecord(
        dataset_id=f"MDS-{suffix}",
        data_version=f"market-{suffix}",
        manifest_path="real_data/quant/test/manifest.json",
        manifest_sha256=(suffix * 6)[:64],
        source_policy_id="SRC-TEST",
        authorization_status="公开行情研究使用已核验",
        adjustment="前复权",
        coverage_start=date(2025, 1, 1),
        coverage_end=date(2025, 12, 31),
        securities=["TEST"],
        capabilities={"capacity_constraint": True},
        limitations=[],
        status="frozen",
        frozen_by="integration",
        frozen_at=now(),
    )
    signal_set = QuantSignalSetRecord(
        signal_set_id=f"QSS-{suffix}",
        name="真实仓储测试",
        version=f"signals-{suffix}",
        content_sha256=(suffix[::-1] * 6)[:64],
        signals=[{"signal_id": "SIG-1"}],
        signal_count=1,
        human_confirmed_only=True,
        evaluation_track="alpha_validation",
        status="frozen",
        frozen_by="integration",
        frozen_at=now(),
    )
    run = QuantBacktestRecord(
        run_id=f"QPF-{suffix}",
        name="持久化闭环",
        market_dataset_id=dataset.dataset_id,
        signal_set_id=signal_set.signal_set_id,
        methodology_version="portfolio-research-v2",
        parameters={"window": 20},
        result={"metrics": {"total_return": "0.01"}},
        evaluation_track="alpha_validation",
        requested_by="integration",
        generated_at=now(),
    )

    uow.quant.add_market_dataset(dataset)
    uow.quant.add_signal_set(signal_set)
    uow.quant.add_backtest(run)
    session.expire_all()

    assert uow.quant.get_market_dataset(dataset.dataset_id) == dataset
    assert uow.quant.get_signal_set(signal_set.signal_set_id) == signal_set
    assert uow.quant.get_backtest(run.run_id) == run
    assert uow.quant.list_backtests("integration")[0].run_id == run.run_id
