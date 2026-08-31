from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from app.core.config import RuleThresholds
from app.core.domain import EvidenceRecord, EvidenceRelationRecord, HypothesisRecord, ThesisRecord
from app.core.enums import (
    ConfirmationStatus,
    ImpactDirection,
    Importance,
    ThesisStatus,
)
from app.services.errors import HumanGateRequired, ValidationFailed
from app.services.permission import Actor
from app.services.relation_review_receipt import (
    RelationReviewReceipt,
    apply_relation_review,
    plan_relation_review,
)
from tests.fakes import build_fake_uow

SHA256 = "a" * 64
REVIEWED_AT = datetime(2026, 8, 31, 18, 7, 44, 236000, tzinfo=timezone(timedelta(hours=8)))


def _uow():
    uow = build_fake_uow()
    uow.thesis.add(
        ThesisRecord(
            thesis_id="THS-1",
            security_id="002594",
            title="比亚迪观察",
            direction="观察",
            core_view="需求与出货",
            established_on=date(2026, 1, 1),
            owner="logic-owner",
            status=ThesisStatus.VALIDATING,
        )
    )
    uow.thesis.add_hypothesis(
        HypothesisRecord(
            hypothesis_id="H1",
            thesis_id="THS-1",
            statement="出口占比提升对冲国内压力",
            hypothesis_type="经营",
            importance=Importance.CORE,
        )
    )
    uow.evidence.add(
        EvidenceRecord(
            evidence_id="EVD-1",
            thesis_id="THS-1",
            hypothesis_id="H1",
            evidence_type="经营事实",
            direction=ImpactDirection.SUPPORT,
            evidence_locator="DOC-1#page-1",
            security_id="002594",
            disclosed_at=datetime(2026, 8, 7, 10, tzinfo=UTC),
        )
    )
    uow.relations.add(
        EvidenceRelationRecord(
            relation_id="REL-1",
            evidence_id="EVD-1",
            thesis_id="THS-1",
            hypothesis_id="H1",
            direction=ImpactDirection.SUPPORT,
            strength="高",
            reason="候选理由",
            status=ConfirmationStatus.PENDING,
            created_by="candidate-builder",
        )
    )
    return uow


def _receipt(**changes) -> RelationReviewReceipt:
    values = {
        "relation_id": "REL-1",
        "evidence_id": "EVD-1",
        "thesis_id": "THS-1",
        "hypothesis_id": "H1",
        "expected_status": ConfirmationStatus.PENDING,
        "expected_direction": ImpactDirection.SUPPORT,
        "expected_strength": "高",
        "expected_reason": "候选理由",
        "decision": "修改",
        "final_direction": ImpactDirection.SUPPORT,
        "final_strength": "中",
        "final_reason": "保留支持方向，但累计销量下降且销量仅为收入代理，因此降为中。",
        "reviewer_id": "FIN-R01",
        "reviewed_at": REVIEWED_AT,
    }
    values.update(changes)
    return RelationReviewReceipt(**values)


def test_review_receipt_plan_is_read_only_and_apply_preserves_researcher_time() -> None:
    uow = _uow()
    operator = Actor("logic-owner")

    plan = plan_relation_review(
        uow,
        receipt=_receipt(),
        operator=operator,
        checked_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    assert uow.relations.get("REL-1").status is ConfirmationStatus.PENDING
    assert plan.after.status is ConfirmationStatus.CONFIRMED
    assert plan.after.direction is ImpactDirection.SUPPORT
    assert plan.after.strength == "中"
    assert plan.after.reviewed_by == "FIN-R01"
    assert plan.after.reviewed_at == REVIEWED_AT

    applied = apply_relation_review(
        uow,
        plan=plan,
        operator=operator,
        receipt_sha256=SHA256,
        thresholds=RuleThresholds(),
    )

    assert applied == uow.relations.get("REL-1")
    audits = uow.audit.list_for_object("evidence_relation", "REL-1")
    assert len(audits) == 1
    assert audits[0].action == "应用外部研究员复核回执"
    assert audits[0].detail["receipt_sha256"] == SHA256
    assert audits[0].detail["before"]["strength"] == "高"
    assert audits[0].detail["after"]["strength"] == "中"


def test_review_receipt_reapplication_is_idempotent() -> None:
    uow = _uow()
    operator = Actor("logic-owner")
    first_plan = plan_relation_review(
        uow,
        receipt=_receipt(),
        operator=operator,
        checked_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    apply_relation_review(
        uow,
        plan=first_plan,
        operator=operator,
        receipt_sha256=SHA256,
        thresholds=RuleThresholds(),
    )

    second_plan = plan_relation_review(
        uow,
        receipt=_receipt(),
        operator=operator,
        checked_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    assert second_plan.already_applied is True
    apply_relation_review(
        uow,
        plan=second_plan,
        operator=operator,
        receipt_sha256=SHA256,
        thresholds=RuleThresholds(),
    )
    assert len(uow.audit.list_for_object("evidence_relation", "REL-1")) == 1


def test_review_receipt_rejects_candidate_snapshot_drift() -> None:
    uow = _uow()
    current = uow.relations.get("REL-1")
    uow.relations.update(replace(current, strength="低"))

    with pytest.raises(ValidationFailed, match="冻结快照"):
        plan_relation_review(
            uow,
            receipt=_receipt(),
            operator=Actor("logic-owner"),
            checked_at=datetime(2026, 9, 1, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    ("reviewed_at", "message"),
    [
        (datetime(2026, 8, 1, tzinfo=UTC), "倒签"),
        (datetime(2026, 9, 2, tzinfo=UTC), "晚于当前时间"),
    ],
)
def test_review_receipt_rejects_invalid_review_time(reviewed_at: datetime, message: str) -> None:
    with pytest.raises(ValidationFailed, match=message):
        plan_relation_review(
            _uow(),
            receipt=_receipt(reviewed_at=reviewed_at),
            operator=Actor("logic-owner"),
            checked_at=datetime(2026, 9, 1, tzinfo=UTC),
        )


def test_review_receipt_requires_logic_owner_as_operator() -> None:
    with pytest.raises(HumanGateRequired, match="逻辑负责人"):
        plan_relation_review(
            _uow(),
            receipt=_receipt(),
            operator=Actor("integration-admin", is_admin=True),
            checked_at=datetime(2026, 9, 1, tzinfo=UTC),
        )
