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

from app.calc.deterministic import Observation, _d
from app.core.config import RuleThresholds
from app.core.enums import (
    ConfirmationStatus,
    ExpectationDirection,
    ImpactDirection,
    Importance,
    ThesisStatus,
)


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


def check_invalidation(
    hypothesis_id: str,
    observations: Sequence[Observation],
    *,
    thesis_established_on: date,
    threshold: Decimal,
    direction: ExpectationDirection,
    thresholds: RuleThresholds,
) -> InvalidationCheck:
    """连续突破阈值判定，按建立日裁剪观察窗口。"""
    in_window = [o for o in observations if o.observation_date >= thesis_established_on]
    excluded = [o.period for o in observations if o.observation_date < thesis_established_on]
    ordered = sorted(in_window, key=lambda o: o.observation_date)

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
        near = close or (consecutive > 0 and consecutive < thresholds.consecutive_breach_periods)

    required = thresholds.consecutive_breach_periods
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


def suggest_status(
    current_status: ThesisStatus,
    evidence: Sequence[EvidenceSummary],
    invalidations: Sequence[InvalidationCheck],
    *,
    thresholds: RuleThresholds,
    next_review_at: date | None = None,
    today: date | None = None,
) -> StatusSuggestion:
    """生成状态建议。优先级：重大风险 > 出现分歧 > 维持当前。"""
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

    if breached:
        triggered = [c.hypothesis_id for c in breached]
        reasons = [
            f"{c.hypothesis_id} 连续 {c.consecutive_breaches} 期突破阈值"
            f"（要求 {c.required_consecutive} 期）；{c.note}"
            for c in breached
        ]
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

    if divergent:
        return StatusSuggestion(
            suggested_status=ThesisStatus.DIVERGENT,
            reasons=[
                f"{e.hypothesis_id} 核心假设同时存在 {e.support_count} 条支持"
                f"和 {e.conflict_count} 条冲突证据"
                for e in divergent
            ],
            triggered_hypotheses=[e.hypothesis_id for e in divergent],
            rule_version=thresholds.version,
        )

    if near:
        reasons = [f"{c.hypothesis_id} 接近失效阈值，建议提高关注但未达失效" for c in near]
        triggered = [c.hypothesis_id for c in near]

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
