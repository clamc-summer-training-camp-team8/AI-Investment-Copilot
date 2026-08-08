"""确定性计算。

PRD 10.3 与 FR-V-001~005：预期差、同比/环比、趋势、简单同业比较全部由程序计算，
AI 只解释结果，不自行计算关键数值。所有数值使用 Decimal，避免样例台账中出现的
浮点残留（如 -0.019999999999999997）。

每个函数返回的结果都携带计算所依赖的口径信息，满足 DA-AC-04「可复核」要求。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from itertools import pairwise

from app.core.enums import ExpectationDirection, ValidationVerdict

QUANT = Decimal("0.000001")


def _d(value: Decimal | int | float | str | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _dd(value: Decimal | int | float | str) -> Decimal:
    """已确认非空的转换。调用方需先过滤 None，否则应走 _d 并处理信息不足分支。"""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


@dataclass(frozen=True)
class Observation:
    """单个指标观测值。period 必须同口径，跨口径比较由调用方拦截。"""

    metric_id: str
    period: str
    observation_date: date
    actual_value: Decimal | None
    unit: str
    period_type: str
    expected_value: Decimal | None = None
    benchmark_value: Decimal | None = None
    source_document_id: str | None = None
    metric_version: str = "v1.0"


@dataclass(frozen=True)
class ExpectationGap:
    """预期差。说明书 Table 13：实际值－预期值，同时给出相对差。"""

    metric_id: str
    period: str
    actual_value: Decimal | None
    expected_value: Decimal | None
    absolute_gap: Decimal | None
    relative_gap: Decimal | None
    verdict: ValidationVerdict
    note: str = ""


@dataclass(frozen=True)
class TrendResult:
    metric_id: str
    periods: list[str]
    values: list[Decimal]
    direction: str
    slope: Decimal | None
    consecutive_decline: int
    consecutive_below_expectation: int
    verdict: ValidationVerdict


@dataclass(frozen=True)
class PeerComparison:
    """简单同业比较。FR-V-003 要求展示同业范围和缺失情况。"""

    metric_id: str
    period: str
    company_value: Decimal | None
    peer_median: Decimal | None
    percentile: Decimal | None
    peer_count: int
    missing_count: int
    peer_scope_version: str
    verdict: ValidationVerdict
    note: str = ""


@dataclass
class CalcAudit:
    """计算审计信息，写入 metric_validation 以支持复算。"""

    metric_id: str
    metric_version: str
    period_type: str
    unit: str
    source_document_ids: list[str] = field(default_factory=list)
    rule_version: str = "rules-v1"


class CalibrationConflictError(ValueError):
    """口径冲突：不同单位或报告期口径禁止直接比较。"""


def _assert_comparable(observations: Sequence[Observation]) -> None:
    """指标管道最低要求：单位、报告期口径一致才允许比较。"""
    if not observations:
        return
    units = {o.unit for o in observations}
    if len(units) > 1:
        raise CalibrationConflictError(f"单位不一致，禁止直接比较: {sorted(units)}")
    period_types = {o.period_type for o in observations}
    if len(period_types) > 1:
        raise CalibrationConflictError(f"报告期口径不一致，禁止混算: {sorted(period_types)}")
    versions = {o.metric_version for o in observations}
    if len(versions) > 1:
        raise CalibrationConflictError(f"指标口径版本不一致: {sorted(versions)}")


def expectation_gap(
    obs: Observation,
    *,
    direction: ExpectationDirection = ExpectationDirection.HIGHER_BETTER,
) -> ExpectationGap:
    """计算预期差并给出规则结论。缺失值不推算，直接返回信息不足。"""
    actual = _d(obs.actual_value)
    expected = _d(obs.expected_value)

    if actual is None or expected is None:
        return ExpectationGap(
            metric_id=obs.metric_id,
            period=obs.period,
            actual_value=actual,
            expected_value=expected,
            absolute_gap=None,
            relative_gap=None,
            verdict=ValidationVerdict.INSUFFICIENT,
            note="实际值或预期值缺失，按口径不推算",
        )

    absolute = (actual - expected).quantize(QUANT)
    relative = ((actual / expected) - Decimal(1)).quantize(QUANT) if expected != 0 else None

    if direction in (
        ExpectationDirection.HIGHER_BETTER,
        ExpectationDirection.NOT_BELOW_THRESHOLD,
    ):
        met = actual >= expected
    else:
        met = actual <= expected

    return ExpectationGap(
        metric_id=obs.metric_id,
        period=obs.period,
        actual_value=actual,
        expected_value=expected,
        absolute_gap=absolute,
        relative_gap=relative,
        verdict=ValidationVerdict.SUPPORT if met else ValidationVerdict.CONFLICT,
        note="" if met else "未达预期，需研究员确认是否调整逻辑",
    )


def period_over_period(current: Observation, previous: Observation) -> ExpectationGap:
    """同比或环比。由调用方按报告期选择对照观测，函数只做差值。"""
    _assert_comparable([current, previous])
    cur, prev = _d(current.actual_value), _d(previous.actual_value)

    if cur is None or prev is None:
        return ExpectationGap(
            metric_id=current.metric_id,
            period=f"{previous.period}->{current.period}",
            actual_value=cur,
            expected_value=prev,
            absolute_gap=None,
            relative_gap=None,
            verdict=ValidationVerdict.INSUFFICIENT,
            note="对照期数据缺失",
        )

    absolute = (cur - prev).quantize(QUANT)
    relative = ((cur / prev) - Decimal(1)).quantize(QUANT) if prev != 0 else None
    return ExpectationGap(
        metric_id=current.metric_id,
        period=f"{previous.period}->{current.period}",
        actual_value=cur,
        expected_value=prev,
        absolute_gap=absolute,
        relative_gap=relative,
        verdict=ValidationVerdict.SUPPORT if absolute >= 0 else ValidationVerdict.CONFLICT,
    )


def trend(
    observations: Sequence[Observation],
    *,
    min_periods: int = 4,
    max_periods: int = 8,
    direction: ExpectationDirection = ExpectationDirection.HIGHER_BETTER,
) -> TrendResult:
    """最近 4-8 期趋势。FR-V-002：不使用复杂预测模型，只给方向、斜率和连续性。"""
    ordered = sorted(observations, key=lambda o: o.observation_date)[-max_periods:]
    _assert_comparable(ordered)
    valued = [o for o in ordered if o.actual_value is not None]

    if len(valued) < min_periods:
        return TrendResult(
            metric_id=ordered[0].metric_id if ordered else "",
            periods=[o.period for o in valued],
            values=[_dd(o.actual_value) for o in valued if o.actual_value is not None],
            direction="信息不足",
            slope=None,
            consecutive_decline=0,
            consecutive_below_expectation=0,
            verdict=ValidationVerdict.INSUFFICIENT,
        )

    values = [_dd(o.actual_value) for o in valued if o.actual_value is not None]
    slope = _ols_slope(values)
    label = "上升" if slope > 0 else "下降" if slope < 0 else "持平"

    decline = 0
    for older, newer in pairwise(values):
        decline = decline + 1 if newer < older else 0

    below = 0
    for o in valued:
        exp = _d(o.expected_value)
        act = _d(o.actual_value)
        if exp is None or act is None:
            below = 0
            continue
        breach = (
            act < exp
            if direction
            in (
                ExpectationDirection.HIGHER_BETTER,
                ExpectationDirection.NOT_BELOW_THRESHOLD,
            )
            else act > exp
        )
        below = below + 1 if breach else 0

    return TrendResult(
        metric_id=valued[0].metric_id,
        periods=[o.period for o in valued],
        values=values,
        direction=label,
        slope=slope,
        consecutive_decline=decline,
        consecutive_below_expectation=below,
        verdict=ValidationVerdict.SUPPORT if slope >= 0 else ValidationVerdict.PARTIAL_CONFLICT,
    )


def _ols_slope(values: Sequence[Decimal]) -> Decimal:
    """最小二乘斜率。等间隔序列，x 取 0..n-1。"""
    n = Decimal(len(values))
    xs = [Decimal(i) for i in range(len(values))]
    mean_x = sum(xs, Decimal(0)) / n
    mean_y = sum(values, Decimal(0)) / n
    num = sum(
        ((x - mean_x) * (y - mean_y) for x, y in zip(xs, values, strict=True)),
        Decimal(0),
    )
    den = sum(((x - mean_x) ** 2 for x in xs), Decimal(0))
    if den == 0:
        return Decimal(0)
    return (num / den).quantize(QUANT)


def peer_comparison(
    company: Observation,
    peers: Sequence[Observation],
    *,
    peer_scope_version: str,
) -> PeerComparison:
    """同业中位数与分位。口径不一致时抛错而非静默比较。"""
    _assert_comparable([company, *peers])
    values = sorted(_dd(p.actual_value) for p in peers if p.actual_value is not None)
    missing = len(peers) - len(values)
    company_value = _d(company.actual_value)

    if not values or company_value is None:
        return PeerComparison(
            metric_id=company.metric_id,
            period=company.period,
            company_value=company_value,
            peer_median=None,
            percentile=None,
            peer_count=len(values),
            missing_count=missing,
            peer_scope_version=peer_scope_version,
            verdict=ValidationVerdict.INSUFFICIENT,
            note="同业样本或公司值缺失，不输出比较结论",
        )

    median = _median(values)
    below = sum(1 for v in values if v < company_value)
    percentile = (Decimal(below) / Decimal(len(values))).quantize(QUANT)

    return PeerComparison(
        metric_id=company.metric_id,
        period=company.period,
        company_value=company_value,
        peer_median=median,
        percentile=percentile,
        peer_count=len(values),
        missing_count=missing,
        peer_scope_version=peer_scope_version,
        verdict=ValidationVerdict.SUPPORT
        if company_value >= median
        else ValidationVerdict.PARTIAL_CONFLICT,
        note=f"同业有效样本 {len(values)} 家，缺失 {missing} 家",
    )


def _median(values: Sequence[Decimal]) -> Decimal:
    n = len(values)
    mid = n // 2
    if n % 2 == 1:
        return values[mid]
    return ((values[mid - 1] + values[mid]) / Decimal(2)).quantize(QUANT)


def excess_return(
    security_return: Decimal | float | str,
    benchmark_return: Decimal | float | str,
) -> Decimal:
    """超额收益 AR = R - Rb。说明书 Table 15，MVP 只做简单基准调整。

    Decimal 计算避免样例台账里 -0.02 被存成 -0.019999999999999997。
    """
    return (_dd(security_return) - _dd(benchmark_return)).quantize(QUANT)
