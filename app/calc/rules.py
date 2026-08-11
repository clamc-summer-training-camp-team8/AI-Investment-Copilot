"""状态建议与失效条件规则引擎。

关键约束（PRD 5.2、5.4）：规则只产生**建议**，正式状态变更必须由负责人确认并填写原因。

重要实现细节：失效条件的连续期数判定必须按 thesis 建立日裁剪观察窗口。样例数据中
2025Q2(11%)、2025Q3(13%) 连续两期低于 15% 预期，但两期都早于逻辑建立日
2026-01-15；若不裁剪，导入样例数据的瞬间就会误判 H2 失效。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from app.calc.deterministic import Observation, _d
from app.core.enums import (
    ConfirmationStatus,
    ExpectationDirection,
    ImpactDirection,
    Importance,
    ThesisStatus,
)


class RuleThresholdsLike(Protocol):
    """Structural contract required by the pure rule engine.

    Keeping this protocol here avoids importing the application settings layer
    (and its optional runtime dependencies) into deterministic calculations.
    ``app.core.config.RuleThresholds`` satisfies this contract unchanged.
    """

    @property
    def version(self) -> str: ...

    @property
    def consecutive_breach_periods(self) -> int: ...

    @property
    def near_invalidation_ratio(self) -> float: ...

    @property
    def divergence_min_support(self) -> int: ...

    @property
    def divergence_min_conflict(self) -> int: ...


@dataclass(frozen=True)
class EvidenceSummary:
    """已确认证据的聚合视图，用于分歧判定。"""

    hypothesis_id: str
    importance: Importance
    support_count: int
    conflict_count: int


@dataclass(frozen=True)
class StatusSuggestion:
    """状态建议。必须携带理由和依据，供人工确认时展示。"""

    suggested_status: ThesisStatus
    reasons: list[str]
    triggered_hypotheses: list[str]
    rule_version: str
    requires_human_confirmation: bool = True


@dataclass(frozen=True)
class InvalidationCheck:
    hypothesis_id: str
    breached: bool
    near_breach: bool
    consecutive_breaches: int
    required_consecutive: int
    evaluated_periods: list[str]
    excluded_periods: list[str]
    note: str


@dataclass(frozen=True)
class ThesisInvalidation:
    """thesis 级失效条件的组合判定结果。

    样例案例的失效条件是「海外收入连续两个季度低于预期 **且** 毛利率低于 18%」。
    单条 InvalidationCheck 判不出这个，因为它只看一个指标。2026Q1 只有毛利率
    不达标（0.17 < 0.18），收入是 0.18 ≥ 0.15，AND 条件不成立，所以正确结论是
    「风险关注」而不是「失效」——这正是标注规范 §6 给出的人工判断答案。
    """

    thesis_id: str
    satisfied: bool
    require_all: bool
    breached_hypotheses: list[str]
    unmet_hypotheses: list[str]
    note: str


def check_invalidation(
    hypothesis_id: str,
    observations: Sequence[Observation],
    *,
    thesis_established_on: date,
    threshold: Decimal,
    direction: ExpectationDirection,
    thresholds: RuleThresholdsLike,
    required_consecutive: int | None = None,
) -> InvalidationCheck:
    """连续突破阈值判定，按建立日裁剪观察窗口。

    ``required_consecutive`` 覆盖全局默认期数。样例案例里 H1/H2 要求连续两期，
    H3「毛利率低于 18%」是单期即标记风险，逐条失效规则的期数不同，来源是
    ``hypothesis_metric_map.invalidation_rule``，不能只用一个全局值。
    """
    in_window = [o for o in observations if o.observation_date >= thesis_established_on]
    excluded = [o.period for o in observations if o.observation_date < thesis_established_on]
    ordered = sorted(in_window, key=lambda o: o.observation_date)

    required = (
        thresholds.consecutive_breach_periods
        if required_consecutive is None
        else max(1, required_consecutive)
    )

    consecutive = 0
    near = False
    for o in ordered:
        actual = _d(o.actual_value)
        if actual is None:
            consecutive = 0
            continue
        if direction in (
            ExpectationDirection.HIGHER_BETTER,
            ExpectationDirection.NOT_BELOW_THRESHOLD,
        ):
            breach = actual < threshold
            close = (
                not breach
                and threshold != 0
                and (actual - threshold) / abs(threshold)
                <= Decimal(str(thresholds.near_invalidation_ratio))
            )
        else:
            breach = actual > threshold
            close = (
                not breach
                and threshold != 0
                and (threshold - actual) / abs(threshold)
                <= Decimal(str(thresholds.near_invalidation_ratio))
            )
        consecutive = consecutive + 1 if breach else 0
        near = close or (consecutive > 0 and consecutive < required)

    breached = consecutive >= required

    note = (
        f"按逻辑建立日 {thesis_established_on} 裁剪，" f"排除 {len(excluded)} 个建立日之前的观察期"
        if excluded
        else "全部观察期均在逻辑建立日之后"
    )

    return InvalidationCheck(
        hypothesis_id=hypothesis_id,
        breached=breached,
        near_breach=near and not breached,
        consecutive_breaches=consecutive,
        required_consecutive=required,
        evaluated_periods=[o.period for o in ordered],
        excluded_periods=excluded,
        note=note,
    )


def evaluate_thesis_invalidation(
    thesis_id: str,
    checks: Sequence[InvalidationCheck],
    *,
    require_all: bool = True,
    participating: Sequence[str] | None = None,
) -> ThesisInvalidation:
    """组合多条假设的失效判定。

    ``require_all=True`` 对应「A 且 B」型失效条件：全部条件成立才算失效。这是
    样例案例的形态，也是默认值——把 AND 误当 OR 会让单个指标不达标就判定整条
    逻辑失效，是本产品最不能犯的错之一（研究员会因为误报而停止信任提醒）。

    ``require_all=False`` 对应「A 或 B」型，任一条件成立即失效。

    ``participating`` 限定参与组合判定的假设。样例案例的 thesis 级失效条件只写了
    收入与毛利率两条，没提行业装机：把无关假设也算进 AND，会让永远达标的那条
    假设永久压住失效判定，等于失效条件失灵。不传则所有 checks 都参与。

    ``checks`` 为空时返回未失效：没有可判定的条件不等于条件成立。

    同理，``participating`` 里的假设**没有对应 check**（指标缺阈值或还没有观测值）
    时按「无法判定」处理，不算成立。否则「收入连续两期低于预期 且 毛利率低于
    18%」会在毛利率还没有数据时退化成只判收入一条，凭一个条件就报失效。
    """
    missing: list[str] = []
    if participating is not None:
        allowed = set(participating)
        checks = [c for c in checks if c.hypothesis_id in allowed]
        evaluated = {c.hypothesis_id for c in checks}
        missing = [h for h in participating if h not in evaluated]

    breached = [c.hypothesis_id for c in checks if c.breached]
    unmet = [c.hypothesis_id for c in checks if not c.breached]

    if not checks:
        satisfied = False
        note = "未配置失效条件或缺少可判定数据，不判定失效"
    elif require_all:
        satisfied = not unmet and not missing
        total = len(checks) + len(missing)
        note = (
            f"失效条件为「全部满足」，{len(breached)}/{total} 条成立"
            if not satisfied
            else f"失效条件为「全部满足」，{total} 条全部成立"
        )
        if not satisfied and unmet:
            note += f"；尚未成立：{'、'.join(unmet)}"
        if missing:
            note += f"；缺少可判定数据：{'、'.join(missing)}"
    else:
        satisfied = bool(breached)
        note = f"失效条件为「任一满足」，成立 {len(breached)} 条"

    return ThesisInvalidation(
        thesis_id=thesis_id,
        satisfied=satisfied,
        require_all=require_all,
        breached_hypotheses=breached,
        unmet_hypotheses=unmet + missing,
        note=note,
    )


def suggest_status(
    current_status: ThesisStatus,
    evidence: Sequence[EvidenceSummary],
    invalidations: Sequence[InvalidationCheck],
    *,
    thresholds: RuleThresholdsLike,
    next_review_at: date | None = None,
    today: date | None = None,
    thesis_invalidation: ThesisInvalidation | None = None,
) -> StatusSuggestion:
    """生成状态建议。优先级：重大风险 > 出现分歧 > 接近/复核提示 > 维持当前。

    ``thesis_invalidation`` 给出组合失效条件的判定结果。传入时以它为准：组合
    条件未成立的情况下，即使单条假设已连续突破，也只建议关注而不建议失效
    （标注规范 §6：仅毛利率不达标 → 未满足全部条件 → 状态改为风险关注）。
    """
    reasons: list[str] = []
    triggered: list[str] = []

    if current_status == ThesisStatus.CLOSED:
        return StatusSuggestion(
            suggested_status=ThesisStatus.CLOSED,
            reasons=["逻辑已关闭，不再生成状态建议"],
            triggered_hypotheses=[],
            rule_version=thresholds.version,
            requires_human_confirmation=False,
        )

    breached = [c for c in invalidations if c.breached]
    near = [c for c in invalidations if c.near_breach]

    # 有组合条件时以组合结论为准；没有则退回「任一突破即建议重大风险」。
    composite_blocks = thesis_invalidation is not None and not thesis_invalidation.satisfied

    if breached and not composite_blocks:
        triggered = [c.hypothesis_id for c in breached]
        reasons = [
            f"{c.hypothesis_id} 连续 {c.consecutive_breaches} 期突破阈值"
            f"（要求 {c.required_consecutive} 期）；{c.note}"
            for c in breached
        ]
        if thesis_invalidation is not None:
            reasons.append(thesis_invalidation.note)
        return StatusSuggestion(
            suggested_status=ThesisStatus.MAJOR_RISK,
            reasons=reasons,
            triggered_hypotheses=triggered,
            rule_version=thresholds.version,
        )

    divergent = [
        e
        for e in evidence
        if e.importance == Importance.CORE
        and e.support_count >= thresholds.divergence_min_support
        and e.conflict_count >= thresholds.divergence_min_conflict
    ]

    # 组合条件拦下了失效判定时，把「哪条已突破、整体为何仍未失效」说清楚。
    # 研究员需要看到这个才能理解为什么状态是关注而不是失效。
    blocked_reasons: list[str] = []
    if breached and composite_blocks and thesis_invalidation is not None:
        blocked_reasons = [
            f"{c.hypothesis_id} 已连续 {c.consecutive_breaches} 期突破阈值" for c in breached
        ]
        blocked_reasons.append(f"但{thesis_invalidation.note}，按关注处理，不判定失效")

    if divergent:
        return StatusSuggestion(
            suggested_status=ThesisStatus.DIVERGENT,
            reasons=[
                f"{e.hypothesis_id} 核心假设同时存在 {e.support_count} 条支持"
                f"和 {e.conflict_count} 条冲突证据"
                for e in divergent
            ]
            + blocked_reasons,
            triggered_hypotheses=[e.hypothesis_id for e in divergent]
            + [c.hypothesis_id for c in breached if composite_blocks],
            rule_version=thresholds.version,
        )

    reasons = list(blocked_reasons)
    triggered = [c.hypothesis_id for c in breached] if composite_blocks else []

    if near:
        reasons += [f"{c.hypothesis_id} 接近失效阈值，建议提高关注但未达失效" for c in near]
        triggered += [c.hypothesis_id for c in near]

    if next_review_at and today and next_review_at <= today:
        reasons.append(f"已到复核日 {next_review_at}，建议发起复核")

    return StatusSuggestion(
        suggested_status=current_status
        if current_status != ThesisStatus.DRAFT
        else ThesisStatus.DRAFT,
        reasons=reasons or ["未触发状态变更条件"],
        triggered_hypotheses=triggered,
        rule_version=thresholds.version,
    )


def summarize_evidence(
    hypothesis_id: str,
    importance: Importance,
    directions: Sequence[tuple[ImpactDirection, ConfirmationStatus]],
) -> EvidenceSummary:
    """只统计已确认证据。待确认和已驳回不参与状态计算。"""
    confirmed = [d for d, s in directions if s == ConfirmationStatus.CONFIRMED]
    return EvidenceSummary(
        hypothesis_id=hypothesis_id,
        importance=importance,
        support_count=sum(1 for d in confirmed if d == ImpactDirection.SUPPORT),
        conflict_count=sum(1 for d in confirmed if d == ImpactDirection.CONFLICT),
    )
