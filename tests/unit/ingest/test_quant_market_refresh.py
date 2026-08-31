from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app.ingest.market_sources import MarketSourceError
from scripts.refresh_quant_market_data import (
    FreshnessObservation,
    assess_freshness,
    candidate_version,
)


def _observations(*, a_date: date, hk_date: date) -> list[FreshnessObservation]:
    benchmark_ids = ("000688", "000913", "399976")
    rows = [FreshnessObservation(item, "benchmark", "A股", a_date, 10, 0) for item in benchmark_ids]
    rows.extend(
        [
            FreshnessObservation("00175", "security", "港股", hk_date, 10, 0),
            FreshnessObservation("09868", "security", "港股", hk_date, 10, 0),
        ]
    )
    return rows


def test_无新交易日返回noop而不是重复构建() -> None:
    decision = assess_freshness(
        current_end=date(2026, 8, 28),
        as_of=date(2026, 8, 31),
        observations=_observations(a_date=date(2026, 8, 28), hk_date=date(2026, 8, 28)),
    )
    assert decision.status == "noop"
    assert decision.target_end == date(2026, 8, 28)


def test_任一市场出现新会话就生成候选决策() -> None:
    decision = assess_freshness(
        current_end=date(2026, 8, 28),
        as_of=date(2026, 8, 31),
        observations=_observations(a_date=date(2026, 8, 31), hk_date=date(2026, 8, 28)),
    )
    assert decision.status == "update_available"
    assert decision.updated_markets == ("A股",)
    assert decision.target_end == date(2026, 8, 31)


def test_A股三个行业基准日期不一致时阻断() -> None:
    rows = _observations(a_date=date(2026, 8, 31), hk_date=date(2026, 8, 31))
    rows[0] = FreshnessObservation(
        rows[0].security_id, "benchmark", "A股", date(2026, 8, 28), 10, 0
    )
    with pytest.raises(MarketSourceError, match="基准最新交易日不一致"):
        assess_freshness(
            current_end=date(2026, 8, 28),
            as_of=date(2026, 8, 31),
            observations=rows,
        )


def test_候选版本复用同日已冻结版本且不覆盖(tmp_path: Path) -> None:
    first, existing = candidate_version(date(2026, 8, 31), root=tmp_path)
    assert first == "akshare-qfq-tushare120-20260831-v1"
    assert existing is None
    destination = tmp_path / first
    destination.mkdir()
    (destination / "manifest.json").write_text(
        json.dumps({"status": "frozen", "coverage": {"start": "2023-12-01", "end": "2026-08-31"}}),
        encoding="utf-8",
    )
    reused, manifest = candidate_version(date(2026, 8, 31), root=tmp_path)
    assert reused == first
    assert manifest == destination / "manifest.json"


def test_候选版本支持显式高权限数据谱系前缀(tmp_path: Path) -> None:
    version, existing = candidate_version(
        date(2026, 8, 31),
        root=tmp_path,
        candidate_prefix="akshare-qfq-tuaremax10000",
    )
    assert version == "akshare-qfq-tuaremax10000-20260831-v1"
    assert existing is None


def test_候选版本拒绝路径型前缀(tmp_path: Path) -> None:
    with pytest.raises(MarketSourceError, match="版本前缀"):
        candidate_version(date(2026, 8, 31), root=tmp_path, candidate_prefix="../escape")
