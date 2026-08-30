"""候选失效阈值的确定性校准工具。

工具只生成带完整依据的候选阈值，不写正式规则。模型不能修改工具结果，后端仍需
经过研究员确认，才能把值写入 ``hypothesis_metric_map``。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Literal

ThresholdMethod = Literal["auto", "sourced_reference", "historical_quantile", "baseline_floor"]


@dataclass(frozen=True)
class ThresholdObservation:
    """一条在特定日期已经公开可得的历史观测。"""

    period: str
    value: Decimal
    available_on: date
    source_id: str


@dataclass(frozen=True)
class ThresholdReference:
    """研究员预期、公司指引或一致预期等有来源的外部参考值。"""

    value: Decimal
    source: str
    recorded_on: date


@dataclass(frozen=True)
class ThresholdSuggestion:
    """可审计的候选阈值；``value=None`` 表示证据不足，不应猜值。"""

    value: Decimal | None
    method: str
    formula: str
    rationale: str
    sample_count: int
    source_periods: tuple[str, ...]
    source_ids: tuple[str, ...]
    confidence: float
    warnings: tuple[str, ...]
    requires_human_review: bool = True


class ThresholdSuggestionTool:
    """根据事前数据窗口或明确外部来源生成候选阈值。"""

    def suggest(
        self,
        *,
        observations: list[ThresholdObservation],
        expected_direction: str,
        as_of: date,
        method: ThresholdMethod = "auto",
        reference: ThresholdReference | None = None,
        quantile: Decimal = Decimal("0.25"),
        rounding_step: Decimal | None = None,
    ) -> ThresholdSuggestion:
        """只使用 ``as_of`` 当日已经可得的数据，防止未来信息泄漏。"""
        if quantile <= 0 or quantile > Decimal("0.5"):
            raise ValueError("quantile 必须位于 0（不含）到 0.5（含），表示失效侧尾部")
        eligible = sorted(
            (item for item in observations if item.available_on <= as_of),
            key=lambda item: (item.available_on, item.period),
        )
        if method == "sourced_reference" or (method == "auto" and reference is not None):
            return self._from_reference(reference, as_of=as_of)
        if method == "baseline_floor":
            return self._baseline_floor(
                eligible,
                expected_direction=expected_direction,
                rounding_step=rounding_step,
            )
        if method == "historical_quantile" and len(eligible) < 8:
            return _insufficient_history(eligible)
        if method == "historical_quantile" or (method == "auto" and len(eligible) >= 8):
            return self._historical_quantile(
                eligible,
                expected_direction=expected_direction,
                quantile=quantile,
                rounding_step=rounding_step,
            )
        return _insufficient_history(eligible)

    @staticmethod
    def _from_reference(
        reference: ThresholdReference | None,
        *,
        as_of: date,
    ) -> ThresholdSuggestion:
        """使用有来源值；记录日晚于校准日时直接拒绝，避免回看偏差。"""
        if reference is None or reference.recorded_on > as_of:
            return ThresholdSuggestion(
                value=None,
                method="invalid_reference",
                formula="未计算",
                rationale="参考值不存在，或在阈值校准日之后才记录。",
                sample_count=0,
                source_periods=(),
                source_ids=(),
                confidence=0.0,
                warnings=("不得使用校准日之后形成的预期。",),
            )
        return ThresholdSuggestion(
            value=reference.value,
            method="sourced_reference",
            formula="阈值 = 已记录且可追溯的研究预期/公司指引",
            rationale=f"采用来源“{reference.source}”在{reference.recorded_on.isoformat()}记录的值。",
            sample_count=1,
            source_periods=(reference.recorded_on.isoformat(),),
            source_ids=(reference.source,),
            confidence=0.85,
            warnings=("来源值仍需研究员确认其口径与目标指标完全一致。",),
        )

    def _historical_quantile(
        self,
        observations: list[ThresholdObservation],
        *,
        expected_direction: str,
        quantile: Decimal,
        rounding_step: Decimal | None,
    ) -> ThresholdSuggestion:
        """以公司自身历史分位生成异常边界，不做跨行业统一阈值。"""
        lower_is_bad = _lower_is_bad(expected_direction)
        effective_quantile = quantile if lower_is_bad else Decimal("1") - quantile
        raw = _quantile([item.value for item in observations], effective_quantile)
        value = _round_outward(raw, step=rounding_step, lower_boundary=lower_is_bad)
        return ThresholdSuggestion(
            value=value,
            method="historical_quantile",
            formula=f"公司自身事前历史的{effective_quantile * 100}%分位",
            rationale="历史分位用于识别偏离公司自身正常区间的异常值，不宣称它是最优预测。",
            sample_count=len(observations),
            source_periods=tuple(item.period for item in observations),
            source_ids=tuple(dict.fromkeys(item.source_id for item in observations)),
            confidence=0.75 if len(observations) >= 12 else 0.65,
            warnings=("需要检查结构性变化、会计口径变化和明显一次性因素。",),
        )

    def _baseline_floor(
        self,
        observations: list[ThresholdObservation],
        *,
        expected_direction: str,
        rounding_step: Decimal | None,
    ) -> ThresholdSuggestion:
        """复现 MVP 单期基线规则，但明确标记低证据强度。"""
        if not observations:
            return ThresholdSuggestion(
                value=None,
                method="insufficient_history",
                formula="未计算",
                rationale="校准日之前没有同口径观测。",
                sample_count=0,
                source_periods=(),
                source_ids=(),
                confidence=0.0,
                warnings=("不得由模型补造基线。",),
            )
        baseline = observations[-1]
        lower_is_bad = _lower_is_bad(expected_direction)
        value = _round_outward(
            baseline.value,
            step=rounding_step,
            lower_boundary=lower_is_bad,
        )
        return ThresholdSuggestion(
            value=value,
            method="baseline_floor",
            formula="阈值 = 校准日前最近一期实际值，按业务精度向失效侧取整",
            rationale="仅用于小样本闭环或研究员明确要求冻结基线的场景。",
            sample_count=len(observations),
            source_periods=(baseline.period,),
            source_ids=(baseline.source_id,),
            confidence=0.4,
            warnings=("单期基线容易受季节性和偶发因素影响，不应宣称为统计阈值。",),
        )


def _insufficient_history(
    observations: list[ThresholdObservation],
) -> ThresholdSuggestion:
    """统一返回证据不足结果，确保显式调用也不能绕过八期下限。"""
    return ThresholdSuggestion(
        value=None,
        method="insufficient_history",
        formula="未计算",
        rationale="缺少有来源参考值，且事前同口径历史少于8期，不生成数值阈值。",
        sample_count=len(observations),
        source_periods=tuple(item.period for item in observations),
        source_ids=tuple(dict.fromkeys(item.source_id for item in observations)),
        confidence=0.0,
        warnings=("可继续积累历史，或由研究员提供公司指引/一致预期来源。",),
    )


def _lower_is_bad(expected_direction: str) -> bool:
    """判断失效侧；无法识别的方向不默认为任意一侧。"""
    if expected_direction in {"越高越好", "不低于阈值"}:
        return True
    if expected_direction in {"越低越好", "不高于阈值"}:
        return False
    raise ValueError(f"不支持的预期方向: {expected_direction}")


def _quantile(values: list[Decimal], q: Decimal) -> Decimal:
    """使用线性插值计算分位数，保持 Decimal 精度和可复算性。"""
    if not values:
        raise ValueError("分位数计算至少需要一个观测值")
    if q < 0 or q > 1:
        raise ValueError("quantile 必须位于 0 到 1")
    ordered = sorted(values)
    position = Decimal(len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - Decimal(lower)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _round_outward(
    value: Decimal,
    *,
    step: Decimal | None,
    lower_boundary: bool,
) -> Decimal:
    """按失效侧取整：下限向下、上限向上，避免取整后变得更激进。"""
    if step is None:
        return value
    if step <= 0:
        raise ValueError("rounding_step 必须大于 0")
    mode = ROUND_FLOOR if lower_boundary else ROUND_CEILING
    return (value / step).to_integral_value(rounding=mode) * step
