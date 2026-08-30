"""研究验证型事件回测引擎。

该模块遵守 ADR-0002：关键收益与风险数值全部由确定性程序计算，AI 不参与计算。
信号只能在生成后的下一可交易日收盘执行；披露时间晚于生成时间的信号会被拒绝，
从计算入口阻断未来数据泄漏。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from math import sqrt

from app.core.timeutil import business_date, is_leakage

RATE_QUANT = Decimal("0.00000001")
MONEY_QUANT = Decimal("0.01")


class BacktestInputError(ValueError):
    """回测输入不满足可复算或时间语义约束。"""


@dataclass(frozen=True)
class MarketBar:
    trading_date: date
    close: Decimal
    benchmark_close: Decimal
    tradable: bool = True


@dataclass(frozen=True)
class StrategySignal:
    signal_id: str
    disclosed_at: datetime
    generated_at: datetime
    score: Decimal


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: Decimal = Decimal("1000000")
    holding_days: int = 20
    transaction_cost_bps: Decimal = Decimal("10")
    slippage_bps: Decimal = Decimal("5")
    allow_short: bool = False


@dataclass(frozen=True)
class EquityPoint:
    trading_date: date
    equity: Decimal
    benchmark_equity: Decimal
    drawdown: Decimal
    position: Decimal


@dataclass(frozen=True)
class TradeRecord:
    signal_id: str
    direction: str
    entry_date: date
    exit_date: date
    entry_price: Decimal
    exit_price: Decimal
    position: Decimal
    gross_return: Decimal
    net_return: Decimal
    holding_days: int
    exit_reason: str


@dataclass(frozen=True)
class BacktestMetrics:
    initial_capital: Decimal
    final_equity: Decimal
    total_return: Decimal
    benchmark_return: Decimal
    excess_return: Decimal
    annualized_return: Decimal
    annualized_volatility: Decimal
    sharpe_ratio: Decimal | None
    max_drawdown: Decimal
    win_rate: Decimal | None
    turnover: Decimal
    trade_count: int
    average_exposure: Decimal


@dataclass(frozen=True)
class BacktestDiagnostics:
    input_signal_count: int
    accepted_signal_count: int
    skipped_signal_count: int
    skipped_signals: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class BacktestResult:
    metrics: BacktestMetrics
    equity_curve: tuple[EquityPoint, ...]
    trades: tuple[TradeRecord, ...]
    diagnostics: BacktestDiagnostics
    methodology_version: str = "event-backtest-v1"


@dataclass
class _OpenTrade:
    signal_id: str
    entry_index: int
    entry_date: date
    entry_price: Decimal
    position: Decimal


def _q_rate(value: Decimal) -> Decimal:
    return value.quantize(RATE_QUANT, rounding=ROUND_HALF_UP)


def _q_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _validate(bars: list[MarketBar], signals: list[StrategySignal], config: BacktestConfig) -> None:
    if len(bars) < 3:
        raise BacktestInputError("至少需要 3 个行情交易日")
    dates = [bar.trading_date for bar in bars]
    if dates != sorted(dates) or len(set(dates)) != len(dates):
        raise BacktestInputError("行情日期必须严格递增且不得重复")
    if any(bar.close <= 0 or bar.benchmark_close <= 0 for bar in bars):
        raise BacktestInputError("收盘价与基准收盘价必须大于 0")
    if config.initial_capital <= 0:
        raise BacktestInputError("初始资金必须大于 0")
    if not 1 <= config.holding_days <= 252:
        raise BacktestInputError("持有期必须在 1~252 个交易日之间")
    if config.transaction_cost_bps < 0 or config.slippage_bps < 0:
        raise BacktestInputError("交易成本与滑点不得为负")
    if config.transaction_cost_bps + config.slippage_bps > 1000:
        raise BacktestInputError("单边交易摩擦不得超过 1000 bps")
    signal_ids = [signal.signal_id for signal in signals]
    if len(set(signal_ids)) != len(signal_ids):
        raise BacktestInputError("signal_id 必须唯一")
    for signal in signals:
        if not signal.signal_id.strip():
            raise BacktestInputError("signal_id 不得为空")
        if signal.generated_at.tzinfo is None or signal.disclosed_at.tzinfo is None:
            raise BacktestInputError(f"信号 {signal.signal_id} 的时间必须包含时区")
        if signal.score < -1 or signal.score > 1:
            raise BacktestInputError(f"信号 {signal.signal_id} 的 score 必须位于 [-1, 1]")


def _execution_index(bars: list[MarketBar], signal: StrategySignal) -> int | None:
    generated_day = business_date(signal.generated_at)
    return next(
        (
            index
            for index, bar in enumerate(bars)
            if bar.trading_date > generated_day and bar.tradable
        ),
        None,
    )


def _scheduled_signals(
    bars: list[MarketBar],
    signals: list[StrategySignal],
) -> tuple[dict[int, list[StrategySignal]], list[str], int]:
    scheduled: dict[int, list[StrategySignal]] = {}
    skipped: list[str] = []
    for signal in sorted(signals, key=lambda item: (item.generated_at, item.signal_id)):
        if is_leakage(signal.disclosed_at, signal.generated_at):
            skipped.append(f"{signal.signal_id}: 生成时间早于公开披露时间，疑似未来数据泄漏")
            continue
        execution_index = _execution_index(bars, signal)
        if execution_index is None:
            skipped.append(f"{signal.signal_id}: 信号之后没有可交易行情")
            continue
        scheduled.setdefault(execution_index, []).append(signal)
    for execution_index, day_signals in scheduled.items():
        if len(day_signals) <= 1:
            continue
        for overridden in day_signals[:-1]:
            skipped.append(f"{overridden.signal_id}: 与更晚信号在同一交易日执行，已被覆盖")
        scheduled[execution_index] = [day_signals[-1]]
    accepted = len(scheduled)
    return scheduled, skipped, accepted


def _target_position(signal: StrategySignal, *, allow_short: bool) -> Decimal:
    score = _q_rate(signal.score)
    return score if allow_short else max(Decimal(0), score)


def _close_trade(
    trade: _OpenTrade,
    *,
    exit_index: int,
    bar: MarketBar,
    friction_rate: Decimal,
    reason: str,
) -> TradeRecord:
    raw_return = bar.close / trade.entry_price - Decimal(1)
    gross_return = raw_return * trade.position
    net_return = gross_return - (abs(trade.position) * friction_rate * Decimal(2))
    return TradeRecord(
        signal_id=trade.signal_id,
        direction="做多" if trade.position > 0 else "做空",
        entry_date=trade.entry_date,
        exit_date=bar.trading_date,
        entry_price=_q_money(trade.entry_price),
        exit_price=_q_money(bar.close),
        position=_q_rate(trade.position),
        gross_return=_q_rate(gross_return),
        net_return=_q_rate(net_return),
        holding_days=max(0, exit_index - trade.entry_index),
        exit_reason=reason,
    )


def _risk_metrics(
    *,
    config: BacktestConfig,
    equity_curve: list[EquityPoint],
    daily_returns: list[Decimal],
    trades: list[TradeRecord],
    turnover: Decimal,
) -> BacktestMetrics:
    final_equity = equity_curve[-1].equity
    total_return = final_equity / config.initial_capital - Decimal(1)
    benchmark_return = equity_curve[-1].benchmark_equity / config.initial_capital - Decimal(1)
    periods = max(1, len(equity_curve) - 1)
    annualized_return = Decimal(
        str((float(final_equity / config.initial_capital) ** (252 / periods)) - 1)
    )

    volatility = Decimal(0)
    sharpe: Decimal | None = None
    if len(daily_returns) >= 2:
        mean = sum(daily_returns, Decimal(0)) / Decimal(len(daily_returns))
        variance = sum(((value - mean) ** 2 for value in daily_returns), Decimal(0)) / Decimal(
            len(daily_returns) - 1
        )
        daily_volatility = Decimal(str(sqrt(float(variance))))
        volatility = daily_volatility * Decimal(str(sqrt(252)))
        if daily_volatility > 0:
            sharpe = mean / daily_volatility * Decimal(str(sqrt(252)))

    wins = sum(1 for trade in trades if trade.net_return > 0)
    average_exposure = sum((abs(point.position) for point in equity_curve), Decimal(0)) / Decimal(
        len(equity_curve)
    )
    return BacktestMetrics(
        initial_capital=_q_money(config.initial_capital),
        final_equity=_q_money(final_equity),
        total_return=_q_rate(total_return),
        benchmark_return=_q_rate(benchmark_return),
        excess_return=_q_rate(total_return - benchmark_return),
        annualized_return=_q_rate(annualized_return),
        annualized_volatility=_q_rate(volatility),
        sharpe_ratio=_q_rate(sharpe) if sharpe is not None else None,
        max_drawdown=min((point.drawdown for point in equity_curve), default=Decimal(0)),
        win_rate=_q_rate(Decimal(wins) / Decimal(len(trades))) if trades else None,
        turnover=_q_rate(turnover),
        trade_count=len(trades),
        average_exposure=_q_rate(average_exposure),
    )


def run_event_backtest(
    bars: list[MarketBar],
    signals: list[StrategySignal],
    config: BacktestConfig,
) -> BacktestResult:
    """运行单证券事件策略回测，返回可复核净值、交易与诊断信息。"""
    _validate(bars, signals, config)
    scheduled, skipped, accepted = _scheduled_signals(bars, signals)
    friction_rate = (config.transaction_cost_bps + config.slippage_bps) / Decimal(10000)

    equity = config.initial_capital
    benchmark_equity = config.initial_capital
    peak = config.initial_capital
    position = Decimal(0)
    expiry_index: int | None = None
    open_trade: _OpenTrade | None = None
    turnover = Decimal(0)
    daily_returns: list[Decimal] = []
    trades: list[TradeRecord] = []
    curve: list[EquityPoint] = []

    for index, bar in enumerate(bars):
        period_start_equity = equity
        if index > 0:
            previous = bars[index - 1]
            security_return = bar.close / previous.close - Decimal(1)
            benchmark_daily = bar.benchmark_close / previous.benchmark_close - Decimal(1)
            strategy_return = position * security_return
            if Decimal(1) + strategy_return <= 0:
                raise BacktestInputError("策略单日亏损达到或超过本金，无法继续计算净值")
            equity *= Decimal(1) + strategy_return
            benchmark_equity *= Decimal(1) + benchmark_daily

        target = position
        exit_reason = ""
        target_signal: StrategySignal | None = None
        if expiry_index is not None and index >= expiry_index and bar.tradable:
            target = Decimal(0)
            exit_reason = "持有期结束"
            expiry_index = None

        day_signals = scheduled.get(index, [])
        if day_signals:
            target_signal = day_signals[-1]
            target = _target_position(target_signal, allow_short=config.allow_short)
            exit_reason = "新信号替换"
            expiry_index = index + config.holding_days if target != 0 else None

        replaces_open_signal = target_signal is not None and open_trade is not None
        if target != position or replaces_open_signal:
            day_turnover = (
                abs(position) + abs(target) if replaces_open_signal else abs(target - position)
            )
            if open_trade is not None:
                trades.append(
                    _close_trade(
                        open_trade,
                        exit_index=index,
                        bar=bar,
                        friction_rate=friction_rate,
                        reason=exit_reason or "仓位变更",
                    )
                )
                open_trade = None
            turnover += day_turnover
            cost_factor = Decimal(1) - day_turnover * friction_rate
            if cost_factor <= 0:
                raise BacktestInputError("交易摩擦导致净值无法计算")
            equity *= cost_factor
            position = target
            if position != 0 and target_signal is not None:
                open_trade = _OpenTrade(
                    signal_id=target_signal.signal_id,
                    entry_index=index,
                    entry_date=bar.trading_date,
                    entry_price=bar.close,
                    position=position,
                )

        if index > 0:
            daily_returns.append(equity / period_start_equity - Decimal(1))

        peak = max(peak, equity)
        drawdown = equity / peak - Decimal(1)
        curve.append(
            EquityPoint(
                trading_date=bar.trading_date,
                equity=_q_money(equity),
                benchmark_equity=_q_money(benchmark_equity),
                drawdown=_q_rate(drawdown),
                position=_q_rate(position),
            )
        )

    if position != 0:
        last_bar = bars[-1]
        if open_trade is not None:
            trades.append(
                _close_trade(
                    open_trade,
                    exit_index=len(bars) - 1,
                    bar=last_bar,
                    friction_rate=friction_rate,
                    reason="回测期结束",
                )
            )
        turnover += abs(position)
        equity_before_liquidation = equity
        equity *= Decimal(1) - abs(position) * friction_rate
        if daily_returns:
            daily_returns[-1] = (Decimal(1) + daily_returns[-1]) * (
                equity / equity_before_liquidation
            ) - Decimal(1)
        position = Decimal(0)
        peak = max(peak, equity)
        curve[-1] = EquityPoint(
            trading_date=last_bar.trading_date,
            equity=_q_money(equity),
            benchmark_equity=curve[-1].benchmark_equity,
            drawdown=_q_rate(equity / peak - Decimal(1)),
            position=Decimal(0),
        )

    warnings = ["结果用于研究验证，不构成交易、评级或调仓建议"]
    if not config.allow_short and any(signal.score < 0 for signal in signals):
        warnings.append("长仓模式下，负向信号仅用于平仓，不建立空头")
    if accepted == 0:
        warnings.append("没有信号进入可交易窗口，策略净值将保持不变")

    metrics = _risk_metrics(
        config=config,
        equity_curve=curve,
        daily_returns=daily_returns,
        trades=trades,
        turnover=turnover,
    )
    return BacktestResult(
        metrics=metrics,
        equity_curve=tuple(curve),
        trades=tuple(trades),
        diagnostics=BacktestDiagnostics(
            input_signal_count=len(signals),
            accepted_signal_count=accepted,
            skipped_signal_count=len(skipped),
            skipped_signals=tuple(skipped),
            warnings=tuple(warnings),
        ),
    )
