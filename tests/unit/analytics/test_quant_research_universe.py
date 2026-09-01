from __future__ import annotations

import json
from decimal import Decimal

import pytest

from analytics.pipelines.quant_price_limit_derivations import (
    load_quant_price_limit_derivations,
)
from analytics.pipelines.quant_research_universe import (
    load_quant_research_governance,
    load_quant_research_universe,
)


def test_p2研究池是纯A股30只分层前瞻样本() -> None:
    universe, protocol = load_quant_research_governance()
    assert universe.universe_id == protocol.universe_id
    assert len(universe.companies) == 30
    assert {company.market for company in universe.companies} == {"A股"}
    assert {company.industry for company in universe.companies} == {
        "芯片半导体",
        "医药",
        "新能源汽车",
    }
    assert all(
        sum(item.industry == industry for item in universe.companies) == 10
        for industry in universe.benchmarks
    )
    assert len(universe.historical_controls) == 3
    assert all(item["signal_eligible"] is False for item in universe.historical_controls)
    assert protocol.partition_for(protocol.prospective_start_at) == "development"
    assert protocol.sample_gate["alpha_claim_allowed"] is False


def test_p2研究池成员资格不能倒签(tmp_path) -> None:
    universe, _ = load_quant_research_governance()
    payload = json.loads(json.dumps(universe.payload, ensure_ascii=False))
    payload["members"][0]["membership_start"] = "2026-08-31"
    path = tmp_path / "universe.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="禁止倒签"):
        load_quant_research_universe(path)


def test_p2涨跌停推导资产只补八条可审计缺口() -> None:
    derivations = load_quant_price_limit_derivations()
    assert derivations.derivation_set_id == "QPLD-sse-20260724-p2a8-v1"
    assert len(derivations.rows) == 8
    assert {item.trading_date.isoformat() for item in derivations.rows} == {"2026-07-24"}
    assert all(item.limit_up is False and item.limit_down is False for item in derivations.rows)
    assert {item.limit_rate for item in derivations.rows} == {Decimal("0.10"), Decimal("0.20")}


def test_p2涨跌停推导价与交易所规则不一致时拒绝加载(tmp_path) -> None:
    derivations = load_quant_price_limit_derivations()
    payload = json.loads(json.dumps(derivations.payload, ensure_ascii=False))
    payload["rows"][0]["upper_limit"] = "999.99"
    path = tmp_path / "price-limit-derivations.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="交易所规则不一致"):
        load_quant_price_limit_derivations(path)
