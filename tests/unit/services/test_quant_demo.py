from __future__ import annotations

from pathlib import Path

import pytest

from app.services.market_data import MarketDataError
from app.services.quant_demo import build_quant_demo_scenario

V4_MANIFEST = (
    Path(__file__).resolve().parents[3]
    / "real_data"
    / "quant"
    / "akshare-qfq-tuaremax10000-p2a30-20260902-v4"
    / "manifest.json"
)
V3_MANIFEST = (
    Path(__file__).resolve().parents[3]
    / "real_data"
    / "quant"
    / "akshare-qfq-tuaremax10000-20260831-v3"
    / "manifest.json"
)


def test_30证券全量确认情景可重复并通过研究候选样本门槛() -> None:
    build_quant_demo_scenario.cache_clear()
    first = build_quant_demo_scenario(V4_MANIFEST)
    second = build_quant_demo_scenario(V4_MANIFEST)

    assert first is second
    assert first["evaluation_track"] == "scenario_simulation"
    assert first["scenario_policy_version"] == "assumed-confirmation-neutral-noop-v1"
    assert first["dataset"]["security_count"] == 30
    assert first["summary"] == {
        "candidate_count": 330,
        "assumed_confirmed_count": 330,
        "directional_signal_count": 264,
        "neutral_noop_count": 66,
        "checkpoint_count": 11,
        "support_count": 132,
        "conflict_count": 132,
    }
    quality = first["result"]["validation_quality"]
    assert quality["status"] == "research_candidate"
    assert quality["unique_security_count"] == 30
    assert quality["nonzero_signal_count"] == 264
    assert quality["active_trading_days"] == 547
    assert quality["alpha_claim_allowed"] is False


def test_中性事件保留审计但不作为平仓信号进入组合计算() -> None:
    scenario = build_quant_demo_scenario(V4_MANIFEST)
    neutral = [item for item in scenario["score_mapping"] if item["direction"] == "中性"]

    assert len(neutral) == 3
    assert all(item["score"] == "0" for item in neutral)
    assert all("保留上一有效状态" in item["portfolio_effect"] for item in neutral)
    assert scenario["result"]["diagnostics"]["input_signal_count"] == 264
    assert scenario["summary"]["candidate_count"] == 264 + 66


def test_演示情景拒绝非30证券冻结数据集() -> None:
    with pytest.raises(MarketDataError, match="恰好 30 只证券"):
        build_quant_demo_scenario(V3_MANIFEST)
