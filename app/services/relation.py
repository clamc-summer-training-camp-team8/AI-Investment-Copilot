"""证据关联管理：新增、修改、解除与人工审核均只影响关联，不覆写来源事实。"""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from app.core.config import RuleThresholds
from app.core.domain import EvidenceRelationRecord, ThesisRecord, UnitOfWork
from app.core.enums import ConfirmationStatus, ImpactDirection
from app.core.timeutil import now
from app.services import audit, demo, status
from app.services.errors import HumanGateRequired, ValidationFailed
from app.services.permission import Actor


def _require_owner(actor: Actor, thesis: ThesisRecord) -> None:
    if thesis.owner != actor.user_id:
        raise HumanGateRequired("只有目标逻辑负责人可以管理证据关联")


def _health_counts(uow: UnitOfWork, thesis_id: str, hypothesis_id: str) -> dict[str, int]:
    relations = [
        item
        for item in uow.relations.list_for_thesis(thesis_id)
        if item.hypothesis_id == hypothesis_id
        and item.status is not ConfirmationStatus.DEACTIVATED
    ]
    return {
        "support_confirmed": sum(
            item.status is ConfirmationStatus.CONFIRMED
            and item.direction is ImpactDirection.SUPPORT
            for item in relations
        ),
        "conflict_confirmed": sum(
            item.status is ConfirmationStatus.CONFIRMED
            and item.direction is ImpactDirection.CONFLICT
            for item in relations
        ),
        "pending": sum(item.status is ConfirmationStatus.PENDING for item in relations),
    }


def _validate_target(uow: UnitOfWork, evidence_id: str, thesis_id: str, hypothesis_id: str) -> ThesisRecord:
    evidence = uow.evidence.get(evidence_id)
    thesis = uow.thesis.get(thesis_id)
    if evidence is None or thesis is None:
        raise ValidationFailed("证据或目标逻辑不存在")
    if evidence.security_id != thesis.security_id:
        raise ValidationFailed("证据只能关联同一证券范围内的逻辑")
    if hypothesis_id not in {item.hypothesis_id for item in uow.thesis.list_hypotheses(thesis_id)}:
        raise ValidationFailed("目标假设不属于所选逻辑")
    return thesis


def create(
    uow: UnitOfWork, *, evidence_id: str, thesis_id: str, hypothesis_id: str,
    direction: ImpactDirection, strength: str | None, reason: str, actor: Actor,
) -> EvidenceRelationRecord:
    thesis = _validate_target(uow, evidence_id, thesis_id, hypothesis_id)
    _require_owner(actor, thesis)
    record = EvidenceRelationRecord(
        relation_id=f"REL-{uuid4().hex[:16]}", evidence_id=evidence_id, thesis_id=thesis_id,
        hypothesis_id=hypothesis_id, direction=direction, strength=strength,
        reason=reason, status=ConfirmationStatus.PENDING, created_by=actor.user_id,
    )
    uow.relations.add(record)
    audit.record(uow.audit, actor=actor.user_id, action="新增证据关联", object_type="evidence_relation", object_id=record.relation_id, detail={"evidence_id": evidence_id, "thesis_id": thesis_id})
    return record


def update(
    uow: UnitOfWork, *, relation_id: str, hypothesis_id: str, direction: ImpactDirection,
    strength: str | None, reason: str, actor: Actor,
) -> EvidenceRelationRecord:
    record = uow.relations.get(relation_id)
    if record is None:
        raise ValidationFailed("证据关联不存在")
    thesis = _validate_target(uow, record.evidence_id, record.thesis_id, hypothesis_id)
    _require_owner(actor, thesis)
    updated = replace(record, hypothesis_id=hypothesis_id, direction=direction, strength=strength, reason=reason, status=ConfirmationStatus.PENDING, reviewed_by=None, reviewed_at=None)
    uow.relations.update(updated)
    audit.record(uow.audit, actor=actor.user_id, action="修改证据关联", object_type="evidence_relation", object_id=relation_id, detail={"reason": reason})
    return updated


def deactivate(uow: UnitOfWork, *, relation_id: str, reason: str, actor: Actor) -> EvidenceRelationRecord:
    record = uow.relations.get(relation_id)
    if record is None:
        raise ValidationFailed("证据关联不存在")
    thesis = uow.thesis.get(record.thesis_id)
    if thesis is None:
        raise ValidationFailed("目标逻辑不存在")
    _require_owner(actor, thesis)
    if not reason.strip():
        raise ValidationFailed("解除关联必须填写原因")
    updated = replace(record, status=ConfirmationStatus.DEACTIVATED, reason=reason, deactivated_by=actor.user_id, deactivated_at=now())
    uow.relations.update(updated)
    audit.record(uow.audit, actor=actor.user_id, action="解除证据关联", object_type="evidence_relation", object_id=relation_id, detail={"reason": reason})
    return updated


def review(
    uow: UnitOfWork, *, relation_id: str, action: str, reason: str | None, actor: Actor, thresholds: RuleThresholds,
) -> tuple[EvidenceRelationRecord, ThesisRecord]:
    record = uow.relations.get(relation_id)
    if record is None:
        raise ValidationFailed("证据关联不存在")
    thesis = uow.thesis.get(record.thesis_id)
    if thesis is None:
        raise ValidationFailed("目标逻辑不存在")
    _require_owner(actor, thesis)
    if action in {"驳回", "暂不判断"} and not (reason or "").strip():
        raise ValidationFailed(f"{action}候选关系必须填写人工判断依据")
    health_before = _health_counts(uow, thesis.thesis_id, record.hypothesis_id)
    if action == "确认":
        updated = replace(record, status=ConfirmationStatus.CONFIRMED, reason=reason or record.reason, reviewed_by=actor.user_id, reviewed_at=now())
    elif action == "驳回":
        updated = replace(record, status=ConfirmationStatus.REJECTED, reason=reason or record.reason, reviewed_by=actor.user_id, reviewed_at=now())
    elif action == "暂不判断":
        updated = replace(record, status=ConfirmationStatus.PENDING, reason=reason or record.reason, reviewed_by=None, reviewed_at=None)
    else:
        raise ValidationFailed("关联审核动作不合法")
    uow.relations.update(updated)
    health_after = _health_counts(uow, thesis.thesis_id, updated.hypothesis_id)
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action=f"关联{action}",
        object_type="evidence_relation",
        object_id=relation_id,
        detail={
            "reason": reason,
            "thesis_id": thesis.thesis_id,
            "hypothesis_id": updated.hypothesis_id,
            "before": {"status": record.status.value},
            "after": {"status": updated.status.value},
        },
    )
    demo.record_timeline(
        uow.audit,
        thesis_id=thesis.thesis_id,
        actor=actor.user_id,
        action=f"关联{action}",
        dimension="human_review",
        event_type="relation_reviewed",
        actor_type="human",
        summary=f"负责人{action}预置 AI 候选关系",
        related_object_type="evidence_relation",
        related_object_id=relation_id,
        before={"status": record.status.value},
        after={"status": updated.status.value},
        reason=reason,
        detail_url=(
            f"/evidence/{record.evidence_id}/analysis?"
            f"thesisId={thesis.thesis_id}&relationId={relation_id}"
        ),
    )
    if health_before != health_after:
        demo.record_timeline(
            uow.audit,
            thesis_id=thesis.thesis_id,
            actor="system",
            action="假设健康度变化",
            dimension="hypothesis_health",
            event_type="hypothesis_health_changed",
            actor_type="system",
            summary=f"假设 {updated.hypothesis_id} 的证据统计已刷新",
            related_object_type="hypothesis",
            related_object_id=updated.hypothesis_id,
            before=health_before,
            after=health_after,
            detail_url=f"/theses/{thesis.thesis_id}#{updated.hypothesis_id}",
        )
    suggestion = status.compute_suggestion(uow, thesis=thesis, hypotheses=uow.thesis.list_hypotheses(thesis.thesis_id), thresholds=thresholds)
    status.record_suggestion(uow, thesis=thesis, suggestion=suggestion, actor=actor.user_id)
    return updated, thesis
