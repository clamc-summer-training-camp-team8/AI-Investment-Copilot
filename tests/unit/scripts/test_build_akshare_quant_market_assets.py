from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from analytics.pipelines.quant_price_limit_derivations import (
    load_quant_price_limit_derivations,
)
from analytics.pipelines.quant_research_universe import load_quant_research_universe
from app.ingest.market_reference_cache import PriceLimitCacheLoad
from app.ingest.market_sources import (
    MarketSourceError,
    PointInTimeSupplement,
    PriceLimitObservation,
)
from scripts.build_akshare_quant_market_assets import _apply_price_limit_derivations


def _snapshot_rows() -> list[dict[str, object]]:
    derivations = load_quant_price_limit_derivations()
    rows: list[dict[str, object]] = []
    for item in derivations.rows:
        rows.extend(
            [
                {
                    "security_id": item.security_id,
                    "trading_date": date(2026, 7, 23),
                    "akshare_raw_close": item.pre_close,
                    "akshare_traded_notional": Decimal("1"),
                    "tushare_raw_close": item.pre_close,
                    "tushare_traded_notional": Decimal("1"),
                },
                {
                    "security_id": item.security_id,
                    "trading_date": item.trading_date,
                    "akshare_raw_close": item.close,
                    "akshare_traded_notional": item.traded_notional,
                    "tushare_raw_close": item.close,
                    "tushare_traded_notional": item.traded_notional,
                },
            ]
        )
    return rows


def test_交易所规则推导只填充双源快照中已核验的缺口() -> None:
    derivations = load_quant_price_limit_derivations()
    universe = load_quant_research_universe()
    supplements = {
        item.security_id: {
            item.trading_date: PointInTimeSupplement(
                market_cap=Decimal("100"), market_cap_observed=True
            )
        }
        for item in derivations.rows
    }

    count = _apply_price_limit_derivations(
        derivations,
        companies=universe.companies,
        start=date(2023, 12, 1),
        end=date(2026, 8, 31),
        cross_source_snapshot=_snapshot_rows(),
        observed_price_limits=PriceLimitCacheLoad({}, (), 0),
        supplements=supplements,
    )

    assert count == 8
    assert all(
        supplements[item.security_id][item.trading_date].price_limit_derived is True
        for item in derivations.rows
    )
    assert all(
        supplements[item.security_id][item.trading_date].price_limit_observed is False
        for item in derivations.rows
    )


def test_直接观测已存在时禁止规则推导覆盖() -> None:
    derivations = load_quant_price_limit_derivations()
    universe = load_quant_research_universe()
    first = derivations.rows[0]
    observed = PriceLimitCacheLoad(
        {
            first.security_id: {
                first.trading_date: PriceLimitObservation(
                    security_id=first.security_id,
                    trading_date=first.trading_date,
                    limit_up=False,
                    limit_down=False,
                )
            }
        },
        (),
        1,
    )

    with pytest.raises(MarketSourceError, match="直接观测已存在"):
        _apply_price_limit_derivations(
            derivations,
            companies=universe.companies,
            start=date(2023, 12, 1),
            end=date(2026, 8, 31),
            cross_source_snapshot=_snapshot_rows(),
            observed_price_limits=observed,
            supplements={},
        )
