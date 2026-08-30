"""研究回测的收益口径、时间穿越保护与交易摩擦。"""

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.calc.backtest import (
    BacktestConfig,
    BacktestInputError,
    MarketBar,
    StrategySignal,
    run_event_backtest,
)

TZ = ZoneInfo("Asia/Shanghai")


def _bars(prices: list[str]) -> list[MarketBar]:
    return [
        MarketBar(
            trading_date=date(2026, 1, 2 + index),
            close=Decimal(price),
            benchmark_close=Decimal("100"),
        )
        for index, price in enumerate(prices)
    ]


def _signal(
    *,
    signal_id: str = "SIG-1",
    disclosed_at: datetime | None = None,
    generated_at: datetime | None = None,
    score: str = "1",
) -> StrategySignal:
    return StrategySignal(
        signal_id=signal_id,
        disclosed_at=disclosed_at or datetime(2026, 1, 2, 9, tzinfo=TZ),
        generated_at=generated_at or datetime(2026, 1, 2, 12, tzinfo=TZ),
        score=Decimal(score),
    )


def test_信号在下一交易日执行并按持有期退出() -> None:
    result = run_event_backtest(
        _bars(["100", "100", "110", "121", "121"]),
        [_signal()],
        BacktestConfig(
            initial_capital=Decimal("1000"),
            holding_days=2,
            transaction_cost_bps=Decimal(0),
            slippage_bps=Decimal(0),
        ),
    )

    assert result.equity_curve[1].position == Decimal("1.00000000")
    assert result.metrics.final_equity == Decimal("1210.00")
    assert result.metrics.total_return == Decimal("0.21000000")
    assert result.metrics.trade_count == 1
    assert result.trades[0].entry_date == date(2026, 1, 3)
    assert result.trades[0].exit_date == date(2026, 1, 5)
    assert result.trades[0].exit_reason == "持有期结束"


def test_生成早于披露的信号被跳过且不产生收益() -> None:
    result = run_event_backtest(
        _bars(["100", "105", "110"]),
        [
            _signal(
                disclosed_at=datetime(2026, 1, 3, 9, tzinfo=TZ),
                generated_at=datetime(2026, 1, 2, 12, tzinfo=TZ),
            )
        ],
        BacktestConfig(),
    )

    assert result.metrics.total_return == Decimal("0E-8")
    assert result.diagnostics.accepted_signal_count == 0
    assert result.diagnostics.skipped_signal_count == 1
    assert "未来数据泄漏" in result.diagnostics.skipped_signals[0]


def test_长仓模式下负向信号平仓但不做空() -> None:
    result = run_event_backtest(
        _bars(["100", "100", "90", "80"]),
        [_signal(score="-1")],
        BacktestConfig(transaction_cost_bps=Decimal(0), slippage_bps=Decimal(0)),
    )

    assert result.metrics.trade_count == 0
    assert result.metrics.total_return == Decimal("0E-8")
    assert any("不建立空头" in warning for warning in result.diagnostics.warnings)


def test_交易成本在建仓和平仓时扣减() -> None:
    result = run_event_backtest(
        _bars(["100", "100", "100"]),
        [_signal()],
        BacktestConfig(
            holding_days=20,
            transaction_cost_bps=Decimal("10"),
            slippage_bps=Decimal(0),
        ),
    )

    assert result.metrics.final_equity < Decimal("1000000")
    assert result.metrics.turnover == Decimal("2.00000000")


def test_新信号替换按完整平仓和再建仓计算换手() -> None:
    result = run_event_backtest(
        _bars(["100", "100", "101", "102", "103"]),
        [
            _signal(signal_id="SIG-1"),
            _signal(
                signal_id="SIG-2",
                disclosed_at=datetime(2026, 1, 3, 9, tzinfo=TZ),
                generated_at=datetime(2026, 1, 3, 12, tzinfo=TZ),
            ),
        ],
        BacktestConfig(
            transaction_cost_bps=Decimal(0),
            slippage_bps=Decimal(0),
        ),
    )

    assert result.metrics.trade_count == 2
    assert result.metrics.turnover == Decimal("4.00000000")
    assert result.trades[0].exit_reason == "新信号替换"


def test_同一执行日只采用最后生成的信号() -> None:
    result = run_event_backtest(
        _bars(["100", "100", "110"]),
        [
            _signal(signal_id="SIG-EARLY", score="-1"),
            _signal(
                signal_id="SIG-LATE",
                generated_at=datetime(2026, 1, 2, 13, tzinfo=TZ),
                score="1",
            ),
        ],
        BacktestConfig(transaction_cost_bps=Decimal(0), slippage_bps=Decimal(0)),
    )

    assert result.diagnostics.accepted_signal_count == 1
    assert result.diagnostics.skipped_signal_count == 1
    assert "同一交易日" in result.diagnostics.skipped_signals[0]
    assert result.trades[0].signal_id == "SIG-LATE"


def test_信号编号重复时拒绝计算() -> None:
    with pytest.raises(BacktestInputError, match="必须唯一"):
        run_event_backtest(
            _bars(["100", "101", "102"]),
            [_signal(signal_id="SAME"), _signal(signal_id="SAME")],
            BacktestConfig(),
        )


def test_行情日期重复时拒绝计算() -> None:
    bars = _bars(["100", "101", "102"])
    bars[1] = MarketBar(date(2026, 1, 2), Decimal("101"), Decimal("100"))
    with pytest.raises(BacktestInputError, match="严格递增"):
        run_event_backtest(bars, [_signal()], BacktestConfig())
