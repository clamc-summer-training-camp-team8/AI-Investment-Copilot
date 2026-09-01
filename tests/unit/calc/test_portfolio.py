from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.calc.portfolio import (
    PortfolioBar,
    PortfolioConfig,
    PortfolioInputError,
    PortfolioSignal,
    run_portfolio_backtest,
)
from app.core.timeutil import BUSINESS_TZ


def _fixture() -> tuple[list[PortfolioBar], list[PortfolioSignal]]:
    start = date(2025, 1, 2)
    bars: list[PortfolioBar] = []
    securities = (
        ("A", "半导体", "100"),
        ("B", "半导体", "200"),
        ("C", "医药", "400"),
        ("D", "医药", "800"),
    )
    for index in range(90):
        day = start + timedelta(days=index)
        for security_index, (security_id, industry, cap) in enumerate(securities):
            price = Decimal(100 + index * (security_index + 1))
            bars.append(
                PortfolioBar(
                    trading_date=day,
                    security_id=security_id,
                    adjusted_close=price,
                    benchmark_close=Decimal(100 + index),
                    industry=industry,
                    market_cap=Decimal(cap) * (Decimal(1) + Decimal(index) / Decimal(1000)),
                    traded_notional=Decimal("10000000"),
                )
            )
    disclosed = datetime(2025, 1, 8, 18, tzinfo=BUSINESS_TZ)
    signals = [
        PortfolioSignal(f"SIG-{security_id}", security_id, disclosed, disclosed, score)
        for security_id, score in (
            ("A", Decimal("1")),
            ("B", Decimal("0.5")),
            ("C", Decimal("-0.4")),
            ("D", Decimal("-1")),
        )
    ]
    return bars, signals


def test_组合引擎输出滚动窗口容量约束与风险归因() -> None:
    bars, signals = _fixture()
    result = run_portfolio_backtest(
        bars,
        signals,
        PortfolioConfig(
            rolling_window_days=10,
            walk_forward_days=15,
            rebalance_days=5,
            max_security_weight=Decimal("0.30"),
            max_industry_weight=Decimal("0.50"),
            neutralize_industry=True,
            neutralize_market_cap=True,
            enforce_capacity=True,
        ),
    )

    assert result.methodology_version == "portfolio-research-v3"
    assert result.metrics.rebalance_count > 0
    assert result.metrics.turnover > 0
    assert result.walk_forward
    assert result.signal_research.observation_count > 0
    assert set(result.signal_research.quantile_returns).issubset({"Q1", "Q2", "Q3", "Q4", "Q5"})
    assert set(result.risk_attribution.security) == {"A", "B", "C", "D"}
    assert set(result.risk_attribution.industry) == {"半导体", "医药"}
    assert "market_beta" in result.risk_attribution.factor_exposure
    assert any("相互独立" in warning for warning in result.diagnostics.warnings)
    assert result.validation_quality.status == "insufficient_sample"
    assert result.validation_quality.alpha_claim_allowed is False
    assert result.metrics.active_start_date is not None
    assert result.metrics.active_end_date is not None


def test_市值中性缺少点时市值时硬失败() -> None:
    bars, signals = _fixture()
    bars = [
        PortfolioBar(**{**bar.__dict__, "market_cap": None}) if bar.security_id == "A" else bar
        for bar in bars
    ]
    with pytest.raises(PortfolioInputError, match="点时市值"):
        run_portfolio_backtest(
            bars,
            signals,
            PortfolioConfig(rolling_window_days=2, neutralize_market_cap=True),
        )


def test_未来数据泄漏信号只隔离不进入组合() -> None:
    bars, _ = _fixture()
    signal = PortfolioSignal(
        "LEAK",
        "A",
        datetime(2025, 2, 1, 18, tzinfo=BUSINESS_TZ),
        datetime(2025, 1, 1, 18, tzinfo=BUSINESS_TZ),
        Decimal(1),
    )
    result = run_portfolio_backtest(
        bars,
        [signal],
        PortfolioConfig(
            rolling_window_days=2,
            neutralize_industry=False,
            neutralize_market_cap=False,
        ),
    )
    assert result.diagnostics.accepted_signal_count == 0
    assert "未来数据泄漏" in result.diagnostics.skipped_signals[0]
    assert result.validation_quality.status == "engineering_test"


def test_行业中性遇到单例行业时硬失败而不是把信号归零() -> None:
    bars, signals = _fixture()
    with pytest.raises(PortfolioInputError, match="单例行业: 半导体"):
        run_portfolio_backtest(
            bars,
            [signals[0]],
            PortfolioConfig(
                rolling_window_days=2,
                neutralize_industry=True,
                neutralize_market_cap=False,
                enforce_capacity=False,
            ),
        )


def test_基准和超额只匹配组合实际暴露日并保留全区间对照() -> None:
    start = date(2025, 1, 1)
    benchmark = ("100", "200", "300", "400", "440", "484")
    bars = [
        PortfolioBar(
            trading_date=start + timedelta(days=index),
            security_id="A",
            adjusted_close=Decimal(100 + index * 10),
            benchmark_close=Decimal(benchmark[index]),
            industry="半导体",
            market_cap=None,
            traded_notional=None,
        )
        for index in range(len(benchmark))
    ]
    generated = datetime(2025, 1, 3, 18, tzinfo=BUSINESS_TZ)
    result = run_portfolio_backtest(
        bars,
        [PortfolioSignal("SIG-A", "A", generated, generated, Decimal(1))],
        PortfolioConfig(
            rolling_window_days=2,
            rebalance_days=1,
            neutralize_industry=False,
            neutralize_market_cap=False,
            enforce_capacity=False,
        ),
    )

    assert result.metrics.active_start_date == date(2025, 1, 4)
    assert result.metrics.active_end_date == date(2025, 1, 6)
    assert result.metrics.active_trading_days == 3
    assert result.metrics.benchmark_return == Decimal("0.21000000")
    assert result.metrics.full_period_benchmark_return == Decimal("3.84000000")
    assert result.metrics.excess_return != result.metrics.full_period_excess_return
