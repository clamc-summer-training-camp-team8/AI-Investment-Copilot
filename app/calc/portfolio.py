"""确定性的多证券组合研究引擎。

这里不做 IO，也不生成订单。输入必须是已经冻结的点时行情与研究信号；行业/市值
中性、容量上限、滚动窗口、IC 和风险归因都由普通程序计算，AI 不参与数值过程。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from math import sqrt

from app.core.timeutil import is_leakage

RATE_QUANT = Decimal("0.00000001")
MONEY_QUANT = Decimal("0.01")


class PortfolioInputError(ValueError):
    """组合回测输入不满足点时、容量或可复算约束。"""


@dataclass(frozen=True)
class PortfolioBar:
    trading_date: date
    security_id: str
    adjusted_close: Decimal
    benchmark_close: Decimal
    industry: str
    market_cap: Decimal | None
    traded_notional: Decimal | None
    tradable: bool = True
    limit_up: bool = False
    limit_down: bool = False


@dataclass(frozen=True)
class PortfolioSignal:
    signal_id: str
    security_id: str
    disclosed_at: datetime
    generated_at: datetime
    score: Decimal


@dataclass(frozen=True)
class PortfolioConfig:
    initial_capital: Decimal = Decimal("1000000")
    rolling_window_days: int = 60
    walk_forward_days: int = 20
    rebalance_days: int = 5
    transaction_cost_bps: Decimal = Decimal("10")
    slippage_bps: Decimal = Decimal("5")
    max_security_weight: Decimal = Decimal("0.20")
    max_industry_weight: Decimal = Decimal("0.40")
    capacity_participation_rate: Decimal = Decimal("0.10")
    neutralize_industry: bool = True
    neutralize_market_cap: bool = True
    enforce_capacity: bool = True
    allow_short: bool = True


@dataclass(frozen=True)
class PortfolioPoint:
    trading_date: date
    equity: Decimal
    benchmark_equity: Decimal
    daily_return: Decimal
    benchmark_return: Decimal
    drawdown: Decimal
    gross_exposure: Decimal
    net_exposure: Decimal
    turnover: Decimal


@dataclass(frozen=True)
class WalkForwardWindow:
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    observation_count: int
    total_return: Decimal
    benchmark_return: Decimal
    excess_return: Decimal


@dataclass(frozen=True)
class PortfolioMetrics:
    initial_capital: Decimal
    final_equity: Decimal
    total_return: Decimal
    benchmark_return: Decimal
    excess_return: Decimal
    annualized_return: Decimal
    annualized_volatility: Decimal
    tracking_error: Decimal
    information_ratio: Decimal | None
    beta: Decimal | None
    max_drawdown: Decimal
    turnover: Decimal
    average_gross_exposure: Decimal
    average_net_exposure: Decimal
    maximum_capacity_utilization: Decimal
    rebalance_count: int


@dataclass(frozen=True)
class SignalResearchMetrics:
    observation_count: int
    ic: Decimal | None
    rank_ic: Decimal | None
    quantile_returns: dict[str, Decimal]


@dataclass(frozen=True)
class RiskAttribution:
    security: dict[str, Decimal]
    industry: dict[str, Decimal]
    factor_exposure: dict[str, Decimal]
    residual: Decimal


@dataclass(frozen=True)
class PortfolioDiagnostics:
    input_signal_count: int
    accepted_signal_count: int
    skipped_signals: tuple[str, ...]
    blocked_trades: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class PortfolioResult:
    metrics: PortfolioMetrics
    equity_curve: tuple[PortfolioPoint, ...]
    walk_forward: tuple[WalkForwardWindow, ...]
    signal_research: SignalResearchMetrics
    risk_attribution: RiskAttribution
    diagnostics: PortfolioDiagnostics
    methodology_version: str = "portfolio-research-v2"


def _q(value: Decimal | int) -> Decimal:
    return Decimal(value).quantize(RATE_QUANT, rounding=ROUND_HALF_UP)


def _money(value: Decimal | int) -> Decimal:
    return Decimal(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _mean(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal(0)) / Decimal(len(values)) if values else Decimal(0)


def _variance(values: list[Decimal]) -> Decimal:
    if len(values) < 2:
        return Decimal(0)
    avg = _mean(values)
    return sum((value - avg) ** 2 for value in values) / Decimal(len(values) - 1)


def _covariance(left: list[Decimal], right: list[Decimal]) -> Decimal:
    if len(left) != len(right) or len(left) < 2:
        return Decimal(0)
    left_avg, right_avg = _mean(left), _mean(right)
    return sum(
        (a - left_avg) * (b - right_avg) for a, b in zip(left, right, strict=True)
    ) / Decimal(len(left) - 1)


def _correlation(left: list[Decimal], right: list[Decimal]) -> Decimal | None:
    left_var, right_var = _variance(left), _variance(right)
    if left_var == 0 or right_var == 0:
        return None
    return _covariance(left, right) / Decimal(sqrt(float(left_var * right_var)))


def _ranks(values: list[Decimal]) -> list[Decimal]:
    """平均秩；并列值不会因输入顺序获得不同排名。"""
    result = [Decimal(0)] * len(values)
    ordered = sorted(range(len(values)), key=lambda index: (values[index], index))
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and values[ordered[end]] == values[ordered[cursor]]:
            end += 1
        rank = (Decimal(cursor + 1) + Decimal(end)) / Decimal(2)
        for index in ordered[cursor:end]:
            result[index] = rank
        cursor = end
    return result


def _validate(
    bars: list[PortfolioBar], signals: list[PortfolioSignal], config: PortfolioConfig
) -> tuple[list[date], list[str], dict[tuple[date, str], PortfolioBar]]:
    if config.initial_capital <= 0:
        raise PortfolioInputError("初始资金必须大于 0")
    if config.rolling_window_days < 2 or config.walk_forward_days < 1 or config.rebalance_days < 1:
        raise PortfolioInputError("滚动、walk-forward 和再平衡窗口必须为正")
    for value, label in (
        (config.max_security_weight, "个股上限"),
        (config.max_industry_weight, "行业上限"),
        (config.capacity_participation_rate, "容量参与率"),
    ):
        if value <= 0 or value > 1:
            raise PortfolioInputError(f"{label}必须在 (0, 1] 内")
    if not bars:
        raise PortfolioInputError("组合回测至少需要一条行情")
    lookup: dict[tuple[date, str], PortfolioBar] = {}
    securities: set[str] = set()
    for bar in bars:
        key = (bar.trading_date, bar.security_id)
        if key in lookup:
            raise PortfolioInputError(f"行情重复: {bar.security_id}/{bar.trading_date}")
        if bar.adjusted_close <= 0 or bar.benchmark_close <= 0:
            raise PortfolioInputError("复权价和基准价必须大于 0")
        if bar.market_cap is not None and bar.market_cap <= 0:
            raise PortfolioInputError("点时市值必须大于 0")
        if bar.traded_notional is not None and bar.traded_notional < 0:
            raise PortfolioInputError("成交额不得小于 0")
        lookup[key] = bar
        securities.add(bar.security_id)
    ids = [signal.signal_id for signal in signals]
    if len(ids) != len(set(ids)):
        raise PortfolioInputError("研究信号编号必须唯一")
    unknown = sorted({signal.security_id for signal in signals} - securities)
    if unknown:
        raise PortfolioInputError(f"信号证券没有冻结行情: {', '.join(unknown)}")
    return sorted({bar.trading_date for bar in bars}), sorted(securities), lookup


def _schedule_signals(
    days: list[date],
    bars_by_security: dict[str, list[PortfolioBar]],
    signals: list[PortfolioSignal],
) -> tuple[dict[date, list[PortfolioSignal]], list[str], int]:
    scheduled: dict[date, list[PortfolioSignal]] = {}
    skipped: list[str] = []
    accepted = 0
    day_set = set(days)
    for signal in sorted(signals, key=lambda item: (item.generated_at, item.signal_id)):
        if is_leakage(signal.disclosed_at, signal.generated_at):
            skipped.append(f"{signal.signal_id}: 生成时间早于披露时间，疑似未来数据泄漏")
            continue
        target = next(
            (
                bar.trading_date
                for bar in bars_by_security[signal.security_id]
                if bar.trading_date > signal.generated_at.date() and bar.tradable
            ),
            None,
        )
        if target is None or target not in day_set:
            skipped.append(f"{signal.signal_id}: 生成后没有可执行交易日")
            continue
        scheduled.setdefault(target, []).append(signal)
        accepted += 1
    return scheduled, skipped, accepted


def _neutral_scores(
    raw: dict[str, Decimal],
    current: dict[str, PortfolioBar],
    config: PortfolioConfig,
) -> tuple[dict[str, Decimal], Decimal]:
    scores = dict(raw)
    if config.neutralize_industry:
        by_industry: dict[str, list[str]] = {}
        for security_id in scores:
            by_industry.setdefault(current[security_id].industry, []).append(security_id)
        for members in by_industry.values():
            avg = _mean([scores[item] for item in members])
            for item in members:
                scores[item] -= avg

    size_exposure = Decimal(0)
    if config.neutralize_market_cap and scores:
        if len(scores) < 3:
            raise PortfolioInputError("市值中性截面至少需要三只证券")
        if any(current[item].market_cap is None for item in scores):
            raise PortfolioInputError("启用市值中性时，每个再平衡截面都必须有点时市值")
        ids = sorted(scores)
        cap_ranks = _ranks([current[item].market_cap or Decimal(0) for item in ids])
        centered = [rank - _mean(cap_ranks) for rank in cap_ranks]
        raw_values = [scores[item] for item in ids]
        denominator = sum(value * value for value in centered)
        beta = (
            sum(score * rank for score, rank in zip(raw_values, centered, strict=True))
            / denominator
            if denominator
            else Decimal(0)
        )
        for item, rank in zip(ids, centered, strict=True):
            scores[item] -= beta * rank
        size_exposure = beta
    return scores, size_exposure


def _constrain_weights(
    scores: dict[str, Decimal],
    current: dict[str, PortfolioBar],
    histories: dict[str, list[PortfolioBar]],
    equity: Decimal,
    config: PortfolioConfig,
) -> tuple[dict[str, Decimal], Decimal]:
    if not config.allow_short:
        scores = {key: max(value, Decimal(0)) for key, value in scores.items()}
    gross = sum((abs(value) for value in scores.values()), Decimal(0))
    weights = {key: value / gross for key, value in scores.items()} if gross else {}
    weights = {
        key: max(-config.max_security_weight, min(config.max_security_weight, value))
        for key, value in weights.items()
    }

    by_industry: dict[str, list[str]] = {}
    for security_id in weights:
        by_industry.setdefault(current[security_id].industry, []).append(security_id)
    for members in by_industry.values():
        industry_gross = sum(abs(weights[item]) for item in members)
        if industry_gross > config.max_industry_weight:
            scale = config.max_industry_weight / industry_gross
            for item in members:
                weights[item] *= scale

    maximum_utilization = Decimal(0)
    if config.enforce_capacity:
        for security_id, weight in list(weights.items()):
            notionals = [
                bar.traded_notional
                for bar in histories[security_id][-20:]
                if bar.traded_notional is not None and bar.traded_notional > 0
            ]
            if not notionals:
                raise PortfolioInputError(f"{security_id} 缺少点时成交额，不能启用容量约束")
            adv20 = _mean([value for value in notionals if value is not None])
            capacity = adv20 * config.capacity_participation_rate
            desired = abs(weight) * equity
            utilization = desired / capacity if capacity else Decimal(0)
            maximum_utilization = max(maximum_utilization, utilization)
            if desired > capacity:
                weights[security_id] = (capacity / equity) * (
                    Decimal(1) if weight > 0 else Decimal(-1)
                )
    return weights, maximum_utilization


def _tradability_adjusted(
    previous: dict[str, Decimal],
    target: dict[str, Decimal],
    current: dict[str, PortfolioBar],
    blocked: list[str],
) -> dict[str, Decimal]:
    adjusted = dict(target)
    for security_id in set(previous) | set(target):
        old, new = previous.get(security_id, Decimal(0)), target.get(security_id, Decimal(0))
        bar = current.get(security_id)
        reason = None
        if bar is None or not bar.tradable:
            reason = "停牌/无可交易行情"
        elif new > old and bar.limit_up:
            reason = "涨停阻止买入"
        elif new < old and bar.limit_down:
            reason = "跌停阻止卖出"
        if reason:
            adjusted[security_id] = old
            blocked.append(f"{bar.trading_date if bar else '未知日期'} {security_id}: {reason}")
    return {key: value for key, value in adjusted.items() if value != 0}


def _window_results(
    points: list[PortfolioPoint], config: PortfolioConfig
) -> tuple[WalkForwardWindow, ...]:
    results: list[WalkForwardWindow] = []
    cursor = config.rolling_window_days
    while cursor < len(points):
        test = points[cursor : cursor + config.walk_forward_days]
        if not test:
            break
        prior_equity = points[cursor - 1].equity
        prior_benchmark = points[cursor - 1].benchmark_equity
        total = test[-1].equity / prior_equity - Decimal(1)
        benchmark = test[-1].benchmark_equity / prior_benchmark - Decimal(1)
        results.append(
            WalkForwardWindow(
                train_start=points[max(0, cursor - config.rolling_window_days)].trading_date,
                train_end=points[cursor - 1].trading_date,
                test_start=test[0].trading_date,
                test_end=test[-1].trading_date,
                observation_count=len(test),
                total_return=_q(total),
                benchmark_return=_q(benchmark),
                excess_return=_q(total - benchmark),
            )
        )
        cursor += config.walk_forward_days
    return tuple(results)


def run_portfolio_backtest(
    bars: list[PortfolioBar],
    signals: list[PortfolioSignal],
    config: PortfolioConfig,
) -> PortfolioResult:
    """运行点时多证券研究回测；不生成任何订单或调仓建议。"""
    days, securities, lookup = _validate(bars, signals, config)
    by_security = {
        security_id: sorted(
            [bar for bar in bars if bar.security_id == security_id],
            key=lambda bar: bar.trading_date,
        )
        for security_id in securities
    }
    scheduled, skipped, accepted = _schedule_signals(days, by_security, signals)
    latest_scores: dict[str, tuple[date, Decimal]] = {}
    weights: dict[str, Decimal] = {}
    equity = benchmark_equity = peak = config.initial_capital
    previous_bars: dict[str, PortfolioBar] = {}
    histories: dict[str, list[PortfolioBar]] = {item: [] for item in securities}
    points: list[PortfolioPoint] = []
    blocked: list[str] = []
    total_turnover = Decimal(0)
    maximum_capacity = Decimal(0)
    rebalance_count = 0
    component_returns: dict[str, list[Decimal]] = {item: [] for item in securities}
    industries = sorted({bar.industry for bar in bars})
    industry_components: dict[str, list[Decimal]] = {item: [] for item in industries}
    factor_size_exposures: list[Decimal] = []
    research_scores: list[Decimal] = []
    research_forwards: list[Decimal] = []

    for day_index, day in enumerate(days):
        current = {
            security_id: lookup[(day, security_id)]
            for security_id in securities
            if (day, security_id) in lookup
        }
        for security_id, bar in current.items():
            histories[security_id].append(bar)

        daily_components: dict[str, Decimal] = {}
        for security_id in securities:
            previous = previous_bars.get(security_id)
            current_bar = current.get(security_id)
            value = (
                weights.get(security_id, Decimal(0))
                * (current_bar.adjusted_close / previous.adjusted_close - Decimal(1))
                if previous is not None and current_bar is not None
                else Decimal(0)
            )
            daily_components[security_id] = value
            component_returns[security_id].append(value)

        strategy_return = sum(daily_components.values(), Decimal(0))
        benchmark_returns = [
            bar.benchmark_close / previous_bars[security_id].benchmark_close - Decimal(1)
            for security_id, bar in current.items()
            if security_id in previous_bars
        ]
        benchmark_return = _mean(benchmark_returns)
        turnover = Decimal(0)

        for signal in scheduled.get(day, []):
            latest_scores[signal.security_id] = (day, signal.score)

        should_rebalance = day_index >= config.rolling_window_days and (
            (day_index - config.rolling_window_days) % config.rebalance_days == 0
            or day in scheduled
        )
        size_exposure = Decimal(0)
        if should_rebalance:
            active = {
                security_id: score
                for security_id, (signal_day, score) in latest_scores.items()
                if (day - signal_day).days <= config.rolling_window_days and security_id in current
            }
            neutral, size_exposure = _neutral_scores(active, current, config)
            target, capacity = _constrain_weights(neutral, current, histories, equity, config)
            target = _tradability_adjusted(weights, target, current, blocked)
            turnover = sum(
                (
                    abs(target.get(item, Decimal(0)) - weights.get(item, Decimal(0)))
                    for item in set(target) | set(weights)
                ),
                Decimal(0),
            )
            friction = (
                turnover * (config.transaction_cost_bps + config.slippage_bps) / Decimal(10000)
            )
            strategy_return -= friction
            total_turnover += turnover
            maximum_capacity = max(maximum_capacity, capacity)
            weights = target
            rebalance_count += 1

            forward_index = day_index + config.rebalance_days
            if forward_index < len(days):
                forward_day = days[forward_index]
                for security_id, score in neutral.items():
                    start_bar = current.get(security_id)
                    end_bar = lookup.get((forward_day, security_id))
                    if start_bar and end_bar:
                        research_scores.append(score)
                        research_forwards.append(
                            end_bar.adjusted_close / start_bar.adjusted_close - Decimal(1)
                        )

        factor_size_exposures.append(size_exposure)
        if Decimal(1) + strategy_return <= 0:
            raise PortfolioInputError(f"{day}: 单日组合损失达到或超过 100%，输入或杠杆无效")
        equity *= Decimal(1) + strategy_return
        benchmark_equity *= Decimal(1) + benchmark_return
        peak = max(peak, equity)
        gross = sum((abs(value) for value in weights.values()), Decimal(0))
        net = sum(weights.values(), Decimal(0))
        points.append(
            PortfolioPoint(
                trading_date=day,
                equity=_money(equity),
                benchmark_equity=_money(benchmark_equity),
                daily_return=_q(strategy_return),
                benchmark_return=_q(benchmark_return),
                drawdown=_q(equity / peak - Decimal(1)),
                gross_exposure=_q(gross),
                net_exposure=_q(net),
                turnover=_q(turnover),
            )
        )
        for industry in industries:
            industry_components[industry].append(
                sum(
                    (
                        value
                        for security_id, value in daily_components.items()
                        if security_id in current and current[security_id].industry == industry
                    ),
                    Decimal(0),
                )
            )
        previous_bars.update(current)

    returns = [point.daily_return for point in points]
    benchmark_returns = [point.benchmark_return for point in points]
    active_returns = [left - right for left, right in zip(returns, benchmark_returns, strict=True)]
    total_return = equity / config.initial_capital - Decimal(1)
    benchmark_total = benchmark_equity / config.initial_capital - Decimal(1)
    periods = max(1, len(points) - 1)
    annualized_return = Decimal((float(equity / config.initial_capital) ** (252 / periods)) - 1)
    volatility = Decimal(sqrt(float(_variance(returns) * Decimal(252))))
    tracking_error = Decimal(sqrt(float(_variance(active_returns) * Decimal(252))))
    information_ratio = (
        _mean(active_returns) * Decimal(252) / tracking_error if tracking_error else None
    )
    benchmark_variance = _variance(benchmark_returns)
    beta = (
        _covariance(returns, benchmark_returns) / benchmark_variance if benchmark_variance else None
    )

    security_risk: dict[str, Decimal] = {}
    variance = _variance(returns)
    for security_id, components in component_returns.items():
        contribution = (
            _covariance(components, returns) / variance * volatility if variance else Decimal(0)
        )
        security_risk[security_id] = _q(contribution)
    industry_risk: dict[str, Decimal] = {}
    for industry, components in industry_components.items():
        contribution = (
            _covariance(components, returns) / variance * volatility if variance else Decimal(0)
        )
        industry_risk[industry] = _q(contribution)
    residual_risk = volatility - sum(security_risk.values(), Decimal(0))

    ic = _correlation(research_scores, research_forwards)
    rank_ic = (
        _correlation(_ranks(research_scores), _ranks(research_forwards))
        if research_scores
        else None
    )
    quantiles: dict[str, Decimal] = {}
    if research_scores:
        ordered = sorted(
            zip(research_scores, research_forwards, strict=True), key=lambda item: item[0]
        )
        for bucket in range(5):
            start = len(ordered) * bucket // 5
            end = len(ordered) * (bucket + 1) // 5
            values = [value for _, value in ordered[start:end]]
            if values:
                quantiles[f"Q{bucket + 1}"] = _q(_mean(values))

    return PortfolioResult(
        metrics=PortfolioMetrics(
            initial_capital=_money(config.initial_capital),
            final_equity=_money(equity),
            total_return=_q(total_return),
            benchmark_return=_q(benchmark_total),
            excess_return=_q(total_return - benchmark_total),
            annualized_return=_q(annualized_return),
            annualized_volatility=_q(volatility),
            tracking_error=_q(tracking_error),
            information_ratio=_q(information_ratio) if information_ratio is not None else None,
            beta=_q(beta) if beta is not None else None,
            max_drawdown=min((point.drawdown for point in points), default=Decimal(0)),
            turnover=_q(total_turnover),
            average_gross_exposure=_q(_mean([point.gross_exposure for point in points])),
            average_net_exposure=_q(_mean([point.net_exposure for point in points])),
            maximum_capacity_utilization=_q(maximum_capacity),
            rebalance_count=rebalance_count,
        ),
        equity_curve=tuple(points),
        walk_forward=_window_results(points, config),
        signal_research=SignalResearchMetrics(
            observation_count=len(research_scores),
            ic=_q(ic) if ic is not None else None,
            rank_ic=_q(rank_ic) if rank_ic is not None else None,
            quantile_returns=quantiles,
        ),
        risk_attribution=RiskAttribution(
            security=security_risk,
            industry=industry_risk,
            factor_exposure={
                "market_beta": _q(beta) if beta is not None else Decimal(0),
                "market_cap_rank": _q(_mean(factor_size_exposures)),
                "average_net": _q(_mean([point.net_exposure for point in points])),
            },
            residual=_q(residual_risk),
        ),
        diagnostics=PortfolioDiagnostics(
            input_signal_count=len(signals),
            accepted_signal_count=accepted,
            skipped_signals=tuple(skipped),
            blocked_trades=tuple(blocked),
            warnings=(
                "仅用于样本外研究验证，不生成订单、评级或调仓指令",
                "语义/检索质量门禁与 Alpha 验证相互独立，回测收益不授予检索放量权限",
            ),
        ),
    )
