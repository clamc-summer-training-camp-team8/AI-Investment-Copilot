"""独立导师裁决；只记录人工结果，不返回模型建议。"""

from __future__ import annotations

from app.core.domain import AdjudicationDecisionRecord, UnitOfWork
from app.services import audit
from app.services.errors import ValidationFailed
from app.services.permission import Actor


def decide(
    uow: UnitOfWork,
    *,
    event_id: str,
    hypothesis: str,
    direction: str,
    reason: str,
    actor: Actor,
) -> AdjudicationDecisionRecord:
    if uow.adjudications.get(event_id) is not None:
        raise ValidationFailed("该样本已经完成裁决，不能重复覆盖独立金标")
    record = uow.adjudications.add(
        AdjudicationDecisionRecord(
            event_id=event_id,
            hypothesis=hypothesis.strip(),
            direction=direction,
            reason=reason.strip(),
            decided_by=actor.user_id,
        )
    )
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action="完成导师裁决",
        object_type="adjudication",
        object_id=event_id,
        detail={"hypothesis": record.hypothesis, "direction": record.direction},
    )
    return record
