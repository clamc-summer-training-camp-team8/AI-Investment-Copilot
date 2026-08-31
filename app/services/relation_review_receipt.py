"""受控应用外部研究员复核回执，不允许回执绕过逻辑负责人闸门。"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from app.core.config import RuleThresholds
from app.core.domain import EvidenceRelationRecord, ThesisRecord, UnitOfWork
from app.core.enums import ConfirmationStatus, ImpactDirection
from app.core.timeutil import now, to_business
from app.services import audit, status
from app.services.errors import HumanGateRequired, ValidationFailed
from app.services.permission import Actor

_RECEIPT_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ACTIONABLE_DECISIONS = frozenset({"通过", "修改", "拒绝"})


@dataclass(frozen=True)
class RelationReviewReceipt:
    relation_id: str
    evidence_id: str
    thesis_id: str
    hypothesis_id: str
    expected_status: ConfirmationStatus
    expected_direction: ImpactDirection
    expected_strength: str | None
    expected_reason: str | None
    decision: str
    final_direction: ImpactDirection
    final_strength: str | None
    final_reason: str
    reviewer_id: str
    reviewed_at: datetime


@dataclass(frozen=True)
class RelationReviewPlan:
    before: EvidenceRelationRecord
    after: EvidenceRelationRecord
    thesis: ThesisRecord
    decision: str
    already_applied: bool


def _same_instant(left: datetime | None, right: datetime) -> bool:
    return left is not None and to_business(left) == to_business(right)


def _target_status(decision: str) -> ConfirmationStatus:
    if decision in {"通过", "修改"}:
        return ConfirmationStatus.CONFIRMED
    if decision == "拒绝":
        return ConfirmationStatus.REJECTED
    raise ValidationFailed("复核回执只允许应用通过、修改或拒绝结论")


def plan_relation_review(
    uow: UnitOfWork,
    *,
    receipt: RelationReviewReceipt,
    operator: Actor,
    checked_at: datetime | None = None,
) -> RelationReviewPlan:
    """校验冻结候选与复核时间，返回不写库的确定性变更计划。"""

    relation = uow.relations.get(receipt.relation_id)
    if relation is None:
        raise ValidationFailed("复核回执对应的证据关联不存在")
    thesis = uow.thesis.get(relation.thesis_id)
    evidence = uow.evidence.get(relation.evidence_id)
    if thesis is None or evidence is None:
        raise ValidationFailed("复核回执对应的证据或投资逻辑不存在")
    if thesis.owner != operator.user_id:
        raise HumanGateRequired("只有目标逻辑负责人可以应用外部研究员复核回执")
    if (
        relation.evidence_id != receipt.evidence_id
        or relation.thesis_id != receipt.thesis_id
        or relation.hypothesis_id != receipt.hypothesis_id
    ):
        raise ValidationFailed("复核对象已漂移：证据、逻辑或假设与冻结回执不一致")
    if receipt.decision not in _ACTIONABLE_DECISIONS:
        raise ValidationFailed("复核回执结论不可应用")
    if not receipt.reviewer_id.strip():
        raise ValidationFailed("复核回执缺少研究员编号")
    if not receipt.final_reason.strip():
        raise ValidationFailed("复核回执缺少最终理由")
    if receipt.reviewed_at.tzinfo is None:
        raise ValidationFailed("复核时间必须包含时区")

    current_time = checked_at or now()
    if current_time.tzinfo is None:
        raise ValidationFailed("校验时间必须包含时区")
    reviewed_at = to_business(receipt.reviewed_at)
    if reviewed_at > to_business(current_time) + timedelta(minutes=5):
        raise ValidationFailed("复核时间晚于当前时间")
    if evidence.disclosed_at is not None and reviewed_at < to_business(evidence.disclosed_at):
        raise ValidationFailed("复核时间早于证据披露时间，存在倒签风险")

    target_status = _target_status(receipt.decision)
    after = replace(
        relation,
        direction=receipt.final_direction,
        strength=receipt.final_strength,
        reason=receipt.final_reason.strip(),
        status=target_status,
        reviewed_by=receipt.reviewer_id.strip(),
        reviewed_at=reviewed_at,
    )
    already_applied = (
        relation.status == target_status
        and relation.direction == after.direction
        and relation.strength == after.strength
        and relation.reason == after.reason
        and relation.reviewed_by == after.reviewed_by
        and _same_instant(relation.reviewed_at, reviewed_at)
    )
    if already_applied:
        return RelationReviewPlan(relation, relation, thesis, receipt.decision, True)

    if (
        relation.status != receipt.expected_status
        or relation.direction != receipt.expected_direction
        or relation.strength != receipt.expected_strength
        or relation.reason != receipt.expected_reason
    ):
        raise ValidationFailed("候选关系已变化，拒绝将复核回执应用到非冻结快照")
    if receipt.decision == "通过" and (
        receipt.final_direction != receipt.expected_direction
        or receipt.final_strength != receipt.expected_strength
    ):
        raise ValidationFailed("“通过”结论不得改写候选方向或强度")
    if receipt.decision == "修改" and (
        receipt.final_direction == receipt.expected_direction
        and receipt.final_strength == receipt.expected_strength
        and receipt.final_reason == receipt.expected_reason
    ):
        raise ValidationFailed("“修改”结论必须至少变更方向、强度或理由")

    return RelationReviewPlan(relation, after, thesis, receipt.decision, False)


def apply_relation_review(
    uow: UnitOfWork,
    *,
    plan: RelationReviewPlan,
    operator: Actor,
    receipt_sha256: str,
    thresholds: RuleThresholds,
) -> EvidenceRelationRecord:
    """原子写入关系与审计；重复应用同一结果时保持幂等。"""

    normalized_sha256 = receipt_sha256.lower()
    if not _RECEIPT_SHA256.fullmatch(normalized_sha256):
        raise ValidationFailed("复核回执 SHA-256 不合法")
    if plan.thesis.owner != operator.user_id:
        raise HumanGateRequired("只有目标逻辑负责人可以应用外部研究员复核回执")
    if plan.already_applied:
        return plan.after

    current = uow.relations.get(plan.before.relation_id)
    if current != plan.before:
        raise ValidationFailed("证据关联在校验后发生变化，请重新执行 dry-run")
    uow.relations.update(plan.after)
    audit.record(
        uow.audit,
        actor=operator.user_id,
        action="应用外部研究员复核回执",
        object_type="evidence_relation",
        object_id=plan.after.relation_id,
        detail={
            "receipt_sha256": normalized_sha256,
            "review_decision": plan.decision,
            "reviewed_by": plan.after.reviewed_by,
            "reviewed_at": plan.after.reviewed_at.isoformat() if plan.after.reviewed_at else None,
            "before": {
                "status": plan.before.status.value,
                "direction": plan.before.direction.value,
                "strength": plan.before.strength,
                "reason": plan.before.reason,
            },
            "after": {
                "status": plan.after.status.value,
                "direction": plan.after.direction.value,
                "strength": plan.after.strength,
                "reason": plan.after.reason,
            },
        },
    )
    suggestion = status.compute_suggestion(
        uow,
        thesis=plan.thesis,
        hypotheses=uow.thesis.list_hypotheses(plan.thesis.thesis_id),
        thresholds=thresholds,
    )
    status.record_suggestion(
        uow,
        thesis=plan.thesis,
        suggestion=suggestion,
        actor=operator.user_id,
    )
    return plan.after
