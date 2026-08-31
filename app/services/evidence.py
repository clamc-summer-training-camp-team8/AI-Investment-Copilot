"""证据确认（FR-R-004）。

四个动作：确认 / 驳回 / 修改关联 / 暂不判断。全部进入反馈与审计。

确认一条证据的完整编排（services/README.md 定义的顺序），全部在一个事务内：

```
permission 校验（证据可见性 ≤ 文档可见性）
  → 写 confirmation_status = 已确认
  → calc 重算证据聚合与失效判定
  → 生成状态建议 → 写 status_suggestion_log
  → 若关键字段变化 → 生成新版本
  → audit 留痕
```

注意最后一步之前**没有**改 `thesis.status`：状态建议停在日志里等人工确认。
"""

from __future__ import annotations

from dataclasses import replace

from app.core.config import RuleThresholds
from app.core.enums import ConfirmationStatus, ImpactDirection, ReviewStatus
from app.core.timeutil import now
from app.ingest.segmentation import parse_locator
from app.services import audit, permission, status
from app.services.errors import NotVisible, ValidationFailed
from app.services.permission import Actor
from app.services.ports import (
    EvidenceRecord,
    HypothesisRecord,
    ThesisRecord,
    UnitOfWork,
)

CONFIRM = "确认"
REJECT = "驳回"
RELINK = "修改关联"
DEFER = "暂不判断"


def create_candidate(
    uow: UnitOfWork,
    *,
    record: EvidenceRecord,
    actor: str = "system",
) -> EvidenceRecord:
    """写入候选证据。

    候选状态恒为待确认——worker 与 AI 都不能把证据推进到已确认
    （workers/README.md：任务链止于候选状态）。
    """
    if record.confirmation_status is not ConfirmationStatus.PENDING:
        raise ValidationFailed("候选证据只能以待确认状态创建，正式确认必须由人工完成")

    parse_locator(record.evidence_locator)  # 格式非法直接抛，不让坏 locator 进证据链

    uow.evidence.add(record)
    audit.record(
        uow.audit,
        actor=actor,
        action="生成候选证据",
        object_type="evidence",
        object_id=record.evidence_id,
        detail={
            "thesis_id": record.thesis_id,
            "hypothesis_id": record.hypothesis_id,
            "direction": record.direction.value,
            "ai_status": record.ai_status,
        },
        model_version=record.model_version,
    )
    return record


def handle(
    uow: UnitOfWork,
    *,
    evidence_id: str,
    action: str,
    actor: Actor,
    thesis: ThesisRecord,
    hypotheses: list[HypothesisRecord],
    thresholds: RuleThresholds,
    note: str | None = None,
    new_hypothesis_id: str | None = None,
    new_direction: ImpactDirection | None = None,
) -> tuple[EvidenceRecord, ThesisRecord]:
    """处置一条候选证据。返回处置后的证据与（未改状态的）逻辑。"""
    record = uow.evidence.get(evidence_id)
    if record is None or record.thesis_id != thesis.thesis_id:
        raise NotVisible(f"证据 {evidence_id} 不存在或无访问权限")

    permission.ensure_thesis_visible(
        actor,
        thesis_id=thesis.thesis_id,
        owner=thesis.owner,
        visibility=thesis.visibility,
        team=thesis.team,
    )

    if action == CONFIRM:
        updated = _confirm(uow, record=record, thesis=thesis, actor=actor, note=note)
        _sync_active_relation_status(
            uow,
            evidence_id=evidence_id,
            thesis_id=thesis.thesis_id,
            confirmation=ConfirmationStatus.CONFIRMED,
            actor=actor,
            note=note,
        )
    elif action == REJECT:
        updated = _simple_update(
            uow,
            record=record,
            actor=actor,
            confirmation=ConfirmationStatus.REJECTED,
            review=ReviewStatus.REJECTED,
            action_label=audit.REJECT,
            note=note,
        )
        _sync_active_relation_status(
            uow,
            evidence_id=evidence_id,
            thesis_id=thesis.thesis_id,
            confirmation=ConfirmationStatus.REJECTED,
            actor=actor,
            note=note,
        )
    elif action == RELINK:
        if not new_hypothesis_id and new_direction is None:
            raise ValidationFailed("修改关联时必须给出新的假设或方向")
        updated = replace(
            record,
            hypothesis_id=new_hypothesis_id or record.hypothesis_id,
            direction=new_direction or record.direction,
            review_status=ReviewStatus.MODIFIED,
            review_note=note,
        )
        uow.evidence.update(updated)
        audit.record(
            uow.audit,
            actor=actor.user_id,
            action="修改证据关联",
            object_type="evidence",
            object_id=evidence_id,
            detail={
                "from_hypothesis": record.hypothesis_id,
                "to_hypothesis": updated.hypothesis_id,
                "from_direction": record.direction.value,
                "to_direction": updated.direction.value,
                "note": note,
            },
        )
    elif action == DEFER:
        updated = _simple_update(
            uow,
            record=record,
            actor=actor,
            confirmation=ConfirmationStatus.PENDING,
            review=ReviewStatus.PENDING,
            action_label="暂不判断",
            note=note,
        )
    else:
        raise ValidationFailed(f"未知的证据处置动作 {action!r}")

    # 处置后重算建议并写日志。状态本身不动。
    suggestion = status.compute_suggestion(
        uow, thesis=thesis, hypotheses=hypotheses, thresholds=thresholds
    )
    status.record_suggestion(uow, thesis=thesis, suggestion=suggestion, actor=actor.user_id)

    return updated, thesis


def _sync_active_relation_status(
    uow: UnitOfWork,
    *,
    evidence_id: str,
    thesis_id: str,
    confirmation: ConfirmationStatus,
    actor: Actor,
    note: str | None,
) -> None:
    """Legacy evidence action and the relation-based radar must observe one status."""

    for relation in uow.relations.list_for_evidence(evidence_id):
        if relation.thesis_id != thesis_id or relation.status is ConfirmationStatus.DEACTIVATED:
            continue
        uow.relations.update(
            replace(
                relation,
                status=confirmation,
                reason=note or relation.reason,
                reviewed_by=actor.user_id,
                reviewed_at=now(),
            )
        )


def _confirm(
    uow: UnitOfWork,
    *,
    record: EvidenceRecord,
    thesis: ThesisRecord,
    actor: Actor,
    note: str | None,
) -> EvidenceRecord:
    """确认进入正式证据链。这一步才做可见性校验。"""
    permission.ensure_evidence_not_wider_than_document(
        evidence_visibility=thesis.visibility,
        document_label=record.source_visibility_label,
    )

    updated = replace(
        record,
        confirmation_status=ConfirmationStatus.CONFIRMED,
        review_status=ReviewStatus.PASSED,
        confirmed_by=actor.user_id,
        confirmed_at=now(),
        review_note=note,
    )
    uow.evidence.update(updated)
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action=audit.CONFIRM,
        object_type="evidence",
        object_id=record.evidence_id,
        detail={
            "hypothesis_id": record.hypothesis_id,
            "direction": record.direction.value,
            "note": note,
        },
        model_version=record.model_version,
    )
    return updated


def _simple_update(
    uow: UnitOfWork,
    *,
    record: EvidenceRecord,
    actor: Actor,
    confirmation: ConfirmationStatus,
    review: ReviewStatus,
    action_label: str,
    note: str | None,
) -> EvidenceRecord:
    updated = replace(
        record,
        confirmation_status=confirmation,
        review_status=review,
        review_note=note,
    )
    uow.evidence.update(updated)
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action=action_label,
        object_type="evidence",
        object_id=record.evidence_id,
        detail={"note": note},
    )
    return updated
