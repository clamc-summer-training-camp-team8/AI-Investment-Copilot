from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from app.services.market_data import FrozenJsonMarketData

MANIFEST = Path("real_data/quant/akshare-qfq-p2a30-20260901-v1/manifest.json")
TUSHARE_MANIFEST = Path(
    "real_data/quant/akshare-qfq-tuaremax10000-p2a30-20260901-v2/manifest.json"
)
RULE_DERIVED_MANIFEST = Path(
    "real_data/quant/akshare-qfq-tuaremax10000-p2a30-20260901-v3/manifest.json"
)


def test_p2候选冻结30只A股公司行动和退市影子样本() -> None:
    adapter = FrozenJsonMarketData(MANIFEST)
    info = adapter.info()
    assert info.dataset_id == "MDS-akshare-qfq-p2a30-20260901-v1"
    assert len(info.securities) == 30
    assert info.capabilities["structured_corporate_action_events"] is True
    assert info.capabilities["historical_universe_and_delisted_samples"] is True
    assert info.capabilities["a_share_point_in_time_market_cap"] is False
    assert info.capabilities["price_limit_status"] is False

    root = MANIFEST.parent
    bars = json.loads((root / "bars.json").read_text(encoding="utf-8"))["rows"]
    assert len(bars) == 19_930
    assert {row["market"] for row in bars} == {"A股"}
    assert {row["currency"] for row in bars} == {"CNY"}

    universe = json.loads((root / "research_universe.json").read_text(encoding="utf-8"))
    assert universe["universe_id"] == "QRU-a-share-30-20260901-v1"
    assert Counter(item["industry"] for item in universe["members"]) == {
        "芯片半导体": 10,
        "医药": 10,
        "新能源汽车": 10,
    }
    protocol = json.loads((root / "sample_protocol.json").read_text(encoding="utf-8"))
    assert protocol["prospective_start_at"] == "2026-09-01T00:00:00+08:00"
    assert protocol["research_candidate_gate"]["alpha_claim_allowed"] is False

    actions = json.loads((root / "corporate_actions.json").read_text(encoding="utf-8"))
    assert len(actions["events"]) == 110
    controls = json.loads((root / "historical_controls.json").read_text(encoding="utf-8"))
    assert len(controls["coverage"]) == 3
    assert len(controls["rows"]) == 1_423
    assert all(row["signal_eligible"] is False for row in controls["rows"])


def test_p2_tushare候选冻结双源对账与点时市值缺口() -> None:
    adapter = FrozenJsonMarketData(TUSHARE_MANIFEST)
    info = adapter.info()
    assert info.dataset_id == "MDS-akshare-qfq-tuaremax10000-p2a30-20260901-v2"
    assert len(info.securities) == 30
    assert info.capabilities["a_share_point_in_time_market_cap"] is True
    assert info.capabilities["tushare_daily_crosscheck"] is True
    assert info.capabilities["tushare_trade_calendar_crosscheck"] is True
    assert info.capabilities["price_limit_status"] is False

    root = TUSHARE_MANIFEST.parent
    bars = json.loads((root / "bars.json").read_text(encoding="utf-8"))["rows"]
    assert len(bars) == 19_930
    assert all(row["market_cap"] is not None for row in bars)

    quality = json.loads((root / "cross_source_quality.json").read_text(encoding="utf-8"))
    assert quality["status"] == "passed"
    assert len(quality["securities"]) == 30
    assert all(item["passed"] is True for item in quality["securities"])
    assert quality["trading_calendar"]["passed"] is True
    assert quality["trading_calendar"]["overlap_open_days"] == 160

    reference = json.loads(
        (root / "tushare_reference_snapshot.json").read_text(encoding="utf-8")
    )
    assert len(reference["market_cap"]["rows"]) == 19_930
    assert len(reference["price_limits"]["rows"]) == 19_922
    expected = {(row["security_id"], row["trading_date"]) for row in bars}
    observed = {
        (row["security_id"], row["trading_date"])
        for row in reference["price_limits"]["rows"]
    }
    assert expected - observed == {
        ("603259", "2026-07-24"),
        ("603501", "2026-07-24"),
        ("603596", "2026-07-24"),
        ("603986", "2026-07-24"),
        ("688008", "2026-07-24"),
        ("688012", "2026-07-24"),
        ("688041", "2026-07-24"),
        ("688981", "2026-07-24"),
    }


def test_p2_v3冻结观测与交易所规则推导的完整涨跌停状态() -> None:
    adapter = FrozenJsonMarketData(RULE_DERIVED_MANIFEST)
    info = adapter.info()
    assert info.dataset_id == "MDS-akshare-qfq-tuaremax10000-p2a30-20260901-v3"
    assert info.capabilities["price_limit_status"] is True
    assert info.capabilities["price_limit_status_fully_observed"] is False
    assert info.capabilities["price_limit_status_rule_derived"] is True

    root = RULE_DERIVED_MANIFEST.parent
    manifest = json.loads(RULE_DERIVED_MANIFEST.read_text(encoding="utf-8"))
    assert "price_limit_derivations" in manifest["assets"]
    bars = json.loads((root / "bars.json").read_text(encoding="utf-8"))["rows"]
    assert len(bars) == 19_930
    assert Counter(row["price_limit_status_source"] for row in bars) == {
        "tushare.stk_limit": 19_922,
        "sse.exchange_rule_derived": 8,
    }
    assert sum(row["limit_up"] is True for row in bars) == 116
    assert sum(row["limit_down"] is True for row in bars) == 34

    reference = json.loads(
        (root / "tushare_reference_snapshot.json").read_text(encoding="utf-8")
    )
    assert reference["schema_version"] == "tushare-reference-snapshot-v2"
    assert reference["price_limits"]["observed_row_count"] == 19_922
    assert reference["price_limits"]["derived_row_count"] == 8
    assert len(reference["price_limits"]["rows"]) == 19_930
    derived = [
        row for row in reference["price_limits"]["rows"] if row["price_limit_derived"]
    ]
    assert {(row["security_id"], row["trading_date"]) for row in derived} == {
        ("603259", "2026-07-24"),
        ("603501", "2026-07-24"),
        ("603596", "2026-07-24"),
        ("603986", "2026-07-24"),
        ("688008", "2026-07-24"),
        ("688012", "2026-07-24"),
        ("688041", "2026-07-24"),
        ("688981", "2026-07-24"),
    }
    assert all(row["limit_up"] is False and row["limit_down"] is False for row in derived)
