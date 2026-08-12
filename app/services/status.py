"""状态建议与人工闸门（PRD 5.2 / 5.4 / FR-S-002、FR-S-003）。

这个模块是整个产品最重要的约束的实现位置，两条硬规则：

1. **规则只产生建议。** `record_suggestion` 只写 `status_suggestion_log`，
   任何情况下都不改 `thesis.status`。
2. **正式状态变更必须由负责人确认并填原因。** `apply_decision` 的 `actor` 与
   `reason` 都不可为空，缺任一直接拒绝。

绕过这条路径修改状态的代码在评审时会被驳回。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from app.calc.deterministic import Observation
from app.calc.rules import (
    EvidenceSummary,
    InvalidationCheck,
    StatusSuggestion,
    check_invalidation,
    evaluate_thesis_invalidation,
    suggest_status,
    summarize_evidence,
)
from app.core.config import RuleThresholds
from app.core.enums import ConfirmationStatus, ThesisStatus
from app.core.timeutil import now
from app.services import audit, version
from app.services.errors import HumanGateRequired, IllegalTransition, ValidationFailed
from app.services.ports import (
    HypothesisRecord,
    SuggestionRecord,
    ThesisRecord,
    UnitOfWork,
)

ACCEPT = "接受"
REJECT = "拒绝"
MODIFY = "修改"

# PRD 5.2 状态机的合法流转。已关闭是终态。
_LEGAL: dict[ThesisStatus, frozenset[ThesisStatus]] = {
    ThesisStatus.DRAFT: frozenset({ThesisStatus.VALIDATING, ThesisStatus.CLOSED}),
    ThesisStatus.VALIDATING: frozenset(
        {ThesisStatus.DIVERGENT, ThesisStatus.MAJOR_RISK, ThesisStatus.CLOSED}
    ),
    ThesisStatus.DIVERGENT: frozenset(
        {ThesisStatus.VALIDATING, ThesisStatus.MAJOR_RISK, ThesisStatus.CLOSED}
    ),
    ThesisStatus.MAJOR_RISK: frozenset(
        {ThesisStatus.VALIDATING, ThesisStatus.DIVERGENT, ThesisStatus.CLOSED}
    ),
    ThesisStatus.CLOSED: frozenset(),
}


def is_legal_transition(current: ThesisStatus, target: ThesisStatus) -> bool:
    if current == target:
        return True
    return target in _LEGAL[current]


def compute_suggestion(
    uow: UnitOfWork,
    *,
    thesis: ThesisRecord,
    hypotheses: list[HypothesisRecord],
    thresholds: RuleThresholds,
    today: date | None = None,
) -> StatusSuggestion:
    """汇总证据与指标，算出状态建议。不写库，不改状态。"""
    # 关联是唯一状态计算来源：同一证据可关联多条逻辑，不能再读取 Evidence 的旧单关联字段。
    relations = uow.relations.list_for_thesis(thesis.thesis_id)
    # 增量迁移与旧单元测试尚未回填关联时，临时兼容旧字段；生产迁移完成后恒走上行。
    legacy_evidence = uow.evidence.list_for_thesis(thesis.thesis_id) if not relations else []

    summaries: list[EvidenceSummary] = []
    checks: list[InvalidationCheck] = []

    for hypothesis in hypotheses:
        related = [
            relation for relation in relations if relation.hypothesis_id == hypothesis.hypothesis_id
        ]
        legacy_related = [
            item for item in legacy_evidence if item.hypothesis_id == hypothesis.hypothesis_id
        ]
        summaries.append(
            summarize_evidence(
                hypothesis.hypothesis_id,
                hypothesis.importance,
                (
                    [(relation.direction, relation.status) for relation in related]
                    if relations
                    else [(item.direction, item.confirmation_status) for item in legacy_related]
                ),
            )
        )

        for mapping in uow.thesis.list_mappings(hypothesis.hypothesis_id):
            # 必须用 `is None` 判断，不能用 `or`。阈值 0 是完全合法的业务取值
            # （「营业收入同比转负则失效」就是阈值 0），而 Decimal("0.00") 为假，
            # 用 `or` 会把它替换成预期值，失效判定从「同比转负」变成「同比低于预期」。
            # 北方华创 2026Q1 同比 +26% 被判失效就是这个原因：26% < 预期 30%。
            threshold = (
                mapping.invalidation_threshold
                if mapping.invalidation_threshold is not None
                else mapping.expected_value
            )
            if threshold is None:
                continue
            observations = [
                Observation(
                    metric_id=o.metric_id,
                    period=o.period,
                    observation_date=o.observation_date,
                    actual_value=o.actual_value,
                    unit=o.unit,
                    period_type=o.period_type,
                    expected_value=o.expected_value,
                    benchmark_value=o.benchmark_value,
                    source_document_id=o.source_document_id,
                    metric_version=o.metric_version,
                )
                for o in uow.observations.list_for_metric(thesis.security_id, mapping.metric_id)
                # 上界裁剪：`today` 之后才可得的观察值不能参与本次判断。
                # `check_invalidation` 只裁剪逻辑成立日之前的数据（下界），没有上界；
                # 少了这一句，用历史时点复算状态时会看到未来的财报（DQ-003 未来信息
                # 泄露）。回溯与复算都依赖这个裁剪，线上按当天跑不受影响。
                if today is None or o.observation_date <= today
            ]
            if not observations:
                continue
            checks.append(
                check_invalidation(
                    hypothesis.hypothesis_id,
                    observations,
                    thesis_established_on=thesis.established_on,
                    threshold=threshold,
                    direction=mapping.expected_direction,
                    thresholds=thresholds,
                    required_consecutive=mapping.invalidation_consecutive_periods,
                )
            )

    composite = evaluate_thesis_invalidation(
        thesis.thesis_id,
        checks,
        require_all=thesis.invalidation_require_all,
        participating=thesis.invalidation_hypotheses or None,
    )

    return suggest_status(
        thesis.status,
        summaries,
        checks,
        thresholds=thresholds,
        next_review_at=thesis.next_review_at,
        today=today,
        thesis_invalidation=composite,
    )


def record_suggestion(
    uow: UnitOfWork,
    *,
    thesis: ThesisRecord,
    suggestion: StatusSuggestion,
    actor: str = "system",
) -> SuggestionRecord:
    """把建议写入日志。

    刻意不接受 thesis 参数的修改：这个函数没有任何路径能改状态，人工确认走
    `apply_decision`。
    """
    saved = uow.suggestions.add(
        SuggestionRecord(
            thesis_id=thesis.thesis_id,
            current_status=thesis.status,
            suggested_status=suggestion.suggested_status,
            reasons=list(suggestion.reasons),
            rule_version=suggestion.rule_version,
            triggered_hypotheses=list(suggestion.triggered_hypotheses),
        )
    )
    audit.record(
        uow.audit,
        actor=actor,
        action="生成状态建议",
        object_type="thesis",
        object_id=thesis.thesis_id,
        detail={
            "suggested_status": suggestion.suggested_status.value,
            "rule_version": suggestion.rule_version,
            "reasons": list(suggestion.reasons),
        },
    )
    return saved


def apply_decision(
    uow: UnitOfWork,
    *,
    thesis: ThesisRecord,
    hypotheses: list[HypothesisRecord],
    suggestion_id: int,
    action: str,
    actor: str,
    reason: str,
    target_status: ThesisStatus | None = None,
) -> ThesisRecord:
    """人工处置状态建议。这是**唯一**能改 thesis.status 的入口。

    `actor` 与 `reason` 都不可为空：FR-S-003 要求负责人接受、拒绝或修改建议时
    填写原因，并生成版本和审计记录。
    """
    if not actor.strip():
        raise HumanGateRequired("状态变更必须记录操作人")
    if not reason.strip():
        raise HumanGateRequired("状态变更必须填写原因（FR-S-003）")
    if action not in (ACCEPT, REJECT, MODIFY):
        raise ValidationFailed(f"未知的处置动作 {action!r}")

    record = uow.suggestions.get(suggestion_id)
    if record is None or record.thesis_id != thesis.thesis_id:
        raise ValidationFailed(f"状态建议 {suggestion_id} 不存在")
    if record.human_action is not None:
        raise ValidationFailed("该建议已被处置，不允许重复处置")

    uow.suggestions.update(
        replace(
            record,
            human_action=action,
            human_reason=reason,
            acted_by=actor,
            acted_at=now(),
        )
    )

    if action == REJECT:
        audit.record(
            uow.audit,
            actor=actor,
            action="拒绝状态建议",
            object_type="thesis",
            object_id=thesis.thesis_id,
            detail={"reason": reason, "suggestion_id": suggestion_id},
        )
        return thesis

    new_status = target_status if action == MODIFY else record.suggested_status
    if new_status is None:
        raise ValidationFailed("修改建议时必须给出目标状态")
    if not is_legal_transition(thesis.status, new_status):
        raise IllegalTransition(f"不允许从 {thesis.status.value} 变更为 {new_status.value}")

    updated = replace(thesis, status=new_status)
    uow.thesis.update(updated)

    version.create(
        uow.versions,
        thesis=updated,
        hypotheses=hypotheses,
        triggered_by=version.TRIGGER_STATUS,
        created_by=actor,
        change_reason=reason,
        changed_fields=["status"],
    )
    audit.record(
        uow.audit,
        actor=actor,
        action=audit.STATUS_CHANGE,
        object_type="thesis",
        object_id=thesis.thesis_id,
        detail={
            "from": thesis.status.value,
            "to": new_status.value,
            "reason": reason,
            "suggestion_id": suggestion_id,
        },
    )
    return updated


def confirmed_evidence_only(status: ConfirmationStatus) -> bool:
    """只有已确认证据进入正式证据链（PRD 4.6）。"""
    return status is ConfirmationStatus.CONFIRMED
