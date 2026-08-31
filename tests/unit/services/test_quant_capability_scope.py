from datetime import date
from decimal import Decimal

import pytest

from app.calc.portfolio import PortfolioBar, PortfolioInputError
from app.services.quant import ensure_market_cap_neutralization_scope


def _bar(*, market_cap: Decimal | None) -> PortfolioBar:
    return PortfolioBar(
        trading_date=date(2026, 8, 28),
        security_id="688981",
        adjusted_close=Decimal("10"),
        benchmark_close=Decimal("20"),
        industry="芯片半导体",
        market_cap=market_cap,
        traded_notional=Decimal("1000000"),
    )


def test_A股专用市值能力允许覆盖完整的所选范围() -> None:
    ensure_market_cap_neutralization_scope(
        {
            "point_in_time_market_cap": False,
            "a_share_point_in_time_market_cap": True,
        },
        [_bar(market_cap=Decimal("100000000"))],
    )


def test_A股专用能力仍拒绝所选范围内的缺口() -> None:
    with pytest.raises(PortfolioInputError, match="所选证券区间"):
        ensure_market_cap_neutralization_scope(
            {"a_share_point_in_time_market_cap": True},
            [_bar(market_cap=None)],
        )


def test_没有冻结能力声明时即使行内有值也拒绝() -> None:
    with pytest.raises(PortfolioInputError, match="已核验点时市值"):
        ensure_market_cap_neutralization_scope({}, [_bar(market_cap=Decimal("100000000"))])
