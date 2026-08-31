from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.services.market_data import FrozenJsonMarketData, MarketDataError


def test_冻结行情同时提供版本日历公司行动契约和容量字段() -> None:
    adapter = FrozenJsonMarketData()
    info = adapter.info()
    assert info.data_version == "akshare-qfq-tushare120-20260830-v1"
    assert info.status == "frozen"
    assert info.authorization_status == "公开行情研究使用已核验"
    assert info.capabilities["trading_calendar"] is True
    assert info.capabilities["capacity_constraint"] is True
    assert info.capabilities["point_in_time_market_cap"] is False
    assert info.capabilities["tushare_daily_crosscheck"] is True
    assert info.capabilities["price_limit_status"] is False
    bars = adapter.bars(("688981",))
    assert bars[0].traded_notional is not None
    assert adapter.trading_days("A股", start=info.coverage_start, end=info.coverage_start)
    assert adapter.corporate_actions("688981") == ()
    assert any("结构化公司行动" in item for item in info.limitations)


def test_冻结资产漂移后拒绝读取(tmp_path: Path) -> None:
    source = Path("real_data/quant/akshare-qfq-tushare120-20260830-v1")
    destination = tmp_path / "dataset"
    shutil.copytree(source, destination)
    payload = json.loads((destination / "bars.json").read_text(encoding="utf-8"))
    payload["rows"][0]["adjusted_close"] = "999"
    (destination / "bars.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MarketDataError, match="哈希漂移"):
        FrozenJsonMarketData(destination / "manifest.json")


def test_任一扩展来源资产漂移也拒绝读取(tmp_path: Path) -> None:
    source = Path("real_data/quant/akshare-qfq-tushare120-20260830-v1")
    destination = tmp_path / "dataset"
    shutil.copytree(source, destination)
    (destination / "provenance.json").write_text("{}", encoding="utf-8")
    with pytest.raises(MarketDataError, match="哈希漂移"):
        FrozenJsonMarketData(destination / "manifest.json")
