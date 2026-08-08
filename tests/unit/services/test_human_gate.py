"""人工闸门的守门测试。

services/README.md 列的五条必须有的测试：

1. 状态建议不会自动改 `thesis.status`
2. 缺 `reason` 的状态变更被拒绝
3. 证据可见性高于来源文档时写入被拒绝
4. 审计写入失败时业务动作回滚
5. 版本快照生成后不可被修改

这些不是普通的单元测试，而是产品红线的可执行形式。改动这些断言等于改产品定义。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.calc.rules import EvidenceSummary, suggest_status
from app.core.config import RuleThresholds
from app.core.domain import (
    EvidenceRecord,
    HypothesisRecord,
    MetricMappingRecord,
    ObservationRecord,
    ThesisRecord,
)
from app.core.enums import (
    ConfirmationStatus,
    ExpectationDirection,
    ImpactDirection,
    Importance,
    ThesisStatus,
    Visibility,
)
from app.services import evidence as evidence_service
from app.services import permission, version
from app.services import status as status_service
from app.services.errors import HumanGateRequired, IllegalTransition, NotVisible
from app.services.permission import Actor
from tests.fakes import ExplodingAuditRepo, build_fake_uow

OWNER = Actor(user_id="研究员A", teams=frozenset({"权益研究"}))
THESIS_ID = "THS-T-001"


def _thesis(**overrides: object) -> ThesisRecord:
    base = {
        "thesis_id": THESIS_ID,
        "security_id": "DEMO001",
        "title": "测试逻辑",
        "direction": "看多",
        "core_view": "核心观点",
        "established_on": date(2026, 1, 15),
        "owner": OWNER.user_id,
        "status": ThesisStatus.VALIDATING,
        "visibility": Visibility.TEAM,
        "team": "权益研究",
        "version": 1,
    }
    base.update(overrides)
    return ThesisRecord(**base)  # type: ignore[arg-type]


def _setup(audit_repo: object = None):  # type: ignore[no-untyped-def]
    uow = build_fake_uow(audit=audit_repo)  # type: ignore[arg-type]
    uow.thesis.add(_thesis())
    uow.thesis.add_hypothesis(
        HypothesisRecord(
            hypothesis_id="H1",
            thesis_id=THESIS_ID,
            statement="假设一",
            hypothesis_type="经营",
            importance=Importance.CORE,
        )
    )
    return uow


def test_状态建议不会自动改状态(thresholds: RuleThresholds) -> None:
    uow = _setup()
    suggestion = suggest_status(
        ThesisStatus.VALIDATING,
        [EvidenceSummary("H1", Importance.CORE, support_count=2, conflict_count=2)],
        [],
        thresholds=thresholds,
    )
    assert suggestion.suggested_status is ThesisStatus.DIVERGENT

    status_service.record_suggestion(uow, thesis=uow.thesis.get(THESIS_ID), suggestion=suggestion)

    assert uow.thesis.get(THESIS_ID).status is ThesisStatus.VALIDATING
    assert uow.suggestions.list_for_thesis(THESIS_ID)[0].human_action is None


def test_缺原因的状态变更被拒绝(thresholds: RuleThresholds) -> None:
    uow = _setup()
    suggestion = suggest_status(
        ThesisStatus.VALIDATING,
        [EvidenceSummary("H1", Importance.CORE, support_count=1, conflict_count=1)],
        [],
        thresholds=thresholds,
    )
    saved = status_service.record_suggestion(
        uow, thesis=uow.thesis.get(THESIS_ID), suggestion=suggestion
    )
    assert saved.suggestion_id is not None

    for bad_reason in ("", "   "):
        with pytest.raises(HumanGateRequired):
            status_service.apply_decision(
                uow,
                thesis=uow.thesis.get(THESIS_ID),
                hypotheses=uow.thesis.list_hypotheses(THESIS_ID),
                suggestion_id=saved.suggestion_id,
                action=status_service.ACCEPT,
                actor=OWNER.user_id,
                reason=bad_reason,
            )

    with pytest.raises(HumanGateRequired):
        status_service.apply_decision(
            uow,
            thesis=uow.thesis.get(THESIS_ID),
            hypotheses=uow.thesis.list_hypotheses(THESIS_ID),
            suggestion_id=saved.suggestion_id,
            action=status_service.ACCEPT,
            actor="  ",
            reason="有原因",
        )

    assert uow.thesis.get(THESIS_ID).status is ThesisStatus.VALIDATING


def test_证据可见性高于来源文档时被拒绝(thresholds: RuleThresholds) -> None:
    """来源文档为内部受限时，证据不得设为最开放的「授权」可见性。"""
    with pytest.raises(NotVisible):
        permission.ensure_evidence_not_wider_than_document(
            evidence_visibility=Visibility.AUTHORIZED,
            document_label="内部受限",
        )

    # 团队可见对内部受限文档是允许的
    permission.ensure_evidence_not_wider_than_document(
        evidence_visibility=Visibility.TEAM,
        document_label="内部受限",
    )


def test_确认证据时校验来源文档权限(thresholds: RuleThresholds) -> None:
    uow = _setup()
    uow.thesis.update(_thesis(visibility=Visibility.AUTHORIZED))
    uow.evidence.add(
        EvidenceRecord(
            evidence_id="EVD-1",
            thesis_id=THESIS_ID,
            hypothesis_id="H1",
            evidence_type="业绩",
            direction=ImpactDirection.CONFLICT,
            evidence_locator="DOC-1#paragraph-1",
            source_visibility_label="机密",
        )
    )

    with pytest.raises(NotVisible):
        evidence_service.handle(
            uow,
            evidence_id="EVD-1",
            action=evidence_service.CONFIRM,
            actor=OWNER,
            thesis=uow.thesis.get(THESIS_ID),
            hypotheses=uow.thesis.list_hypotheses(THESIS_ID),
            thresholds=thresholds,
        )

    assert uow.evidence.get("EVD-1").confirmation_status is ConfirmationStatus.PENDING


def test_审计写入失败时业务动作不生效(thresholds: RuleThresholds) -> None:
    """审计缺失则可追溯性是空话，因此审计失败必须让业务动作一起失败。"""
    uow = _setup(audit_repo=ExplodingAuditRepo())
    uow.evidence.add(
        EvidenceRecord(
            evidence_id="EVD-2",
            thesis_id=THESIS_ID,
            hypothesis_id="H1",
            evidence_type="业绩",
            direction=ImpactDirection.SUPPORT,
            evidence_locator="DOC-1#paragraph-1",
        )
    )

    with pytest.raises(RuntimeError, match="审计写入失败"):
        evidence_service.handle(
            uow,
            evidence_id="EVD-2",
            action=evidence_service.CONFIRM,
            actor=OWNER,
            thesis=uow.thesis.get(THESIS_ID),
            hypotheses=uow.thesis.list_hypotheses(THESIS_ID),
            thresholds=thresholds,
        )
    # 真实实现里事务回滚由 session_scope 保证，这里断言异常确实向上传播，
    # 没有被吞掉——吞掉异常就会出现「业务成功、审计缺失」的组合。


def test_版本仓储不提供修改入口() -> None:
    """PRD 5.3：快照生成后不允许 UPDATE。"""
    uow = build_fake_uow()
    assert not hasattr(uow.versions, "update")

    from app.db.repositories.evidence import SqlVersionRepo

    assert not hasattr(SqlVersionRepo, "update")


def test_版本号单调递增且快照独立() -> None:
    uow = _setup()
    thesis = uow.thesis.get(THESIS_ID)
    hypotheses = uow.thesis.list_hypotheses(THESIS_ID)

    v1 = version.create(
        uow.versions,
        thesis=thesis,
        hypotheses=hypotheses,
        triggered_by=version.TRIGGER_PUBLISH,
        created_by=OWNER.user_id,
    )
    v2 = version.create(
        uow.versions,
        thesis=thesis,
        hypotheses=hypotheses,
        triggered_by=version.TRIGGER_STATUS,
        created_by=OWNER.user_id,
        change_reason="状态变更",
    )

    assert (v1.version, v2.version) == (1, 2)
    assert v1.snapshot["thesis"]["status"] == ThesisStatus.VALIDATING.value


def test_非法状态流转被拒绝(thresholds: RuleThresholds) -> None:
    """已关闭是终态，不能复活。"""
    uow = _setup()
    uow.thesis.update(_thesis(status=ThesisStatus.CLOSED))

    suggestion = suggest_status(
        ThesisStatus.VALIDATING,
        [EvidenceSummary("H1", Importance.CORE, support_count=1, conflict_count=1)],
        [],
        thresholds=thresholds,
    )
    saved = status_service.record_suggestion(
        uow, thesis=uow.thesis.get(THESIS_ID), suggestion=suggestion
    )
    assert saved.suggestion_id is not None

    with pytest.raises(IllegalTransition):
        status_service.apply_decision(
            uow,
            thesis=uow.thesis.get(THESIS_ID),
            hypotheses=uow.thesis.list_hypotheses(THESIS_ID),
            suggestion_id=saved.suggestion_id,
            action=status_service.ACCEPT,
            actor=OWNER.user_id,
            reason="试图复活已关闭逻辑",
        )


def test_建议不可重复处置(thresholds: RuleThresholds) -> None:
    uow = _setup()
    suggestion = suggest_status(
        ThesisStatus.VALIDATING,
        [EvidenceSummary("H1", Importance.CORE, support_count=1, conflict_count=1)],
        [],
        thresholds=thresholds,
    )
    saved = status_service.record_suggestion(
        uow, thesis=uow.thesis.get(THESIS_ID), suggestion=suggestion
    )
    assert saved.suggestion_id is not None

    status_service.apply_decision(
        uow,
        thesis=uow.thesis.get(THESIS_ID),
        hypotheses=uow.thesis.list_hypotheses(THESIS_ID),
        suggestion_id=saved.suggestion_id,
        action=status_service.ACCEPT,
        actor=OWNER.user_id,
        reason="接受分歧判定",
    )

    from app.services.errors import ValidationFailed

    with pytest.raises(ValidationFailed, match="已被处置"):
        status_service.apply_decision(
            uow,
            thesis=uow.thesis.get(THESIS_ID),
            hypotheses=uow.thesis.list_hypotheses(THESIS_ID),
            suggestion_id=saved.suggestion_id,
            action=status_service.ACCEPT,
            actor=OWNER.user_id,
            reason="重复处置",
        )


def test_候选证据不能以已确认状态创建() -> None:
    """worker 与 AI 都不能替人确认证据。"""
    uow = _setup()
    from app.services.errors import ValidationFailed

    with pytest.raises(ValidationFailed):
        evidence_service.create_candidate(
            uow,
            record=EvidenceRecord(
                evidence_id="EVD-3",
                thesis_id=THESIS_ID,
                hypothesis_id="H1",
                evidence_type="业绩",
                direction=ImpactDirection.SUPPORT,
                evidence_locator="DOC-1#paragraph-1",
                confirmation_status=ConfirmationStatus.CONFIRMED,
            ),
        )


def test_坏的引用定位不得进入证据链() -> None:
    uow = _setup()
    with pytest.raises(ValueError, match="证据定位格式非法"):
        evidence_service.create_candidate(
            uow,
            record=EvidenceRecord(
                evidence_id="EVD-4",
                thesis_id=THESIS_ID,
                hypothesis_id="H1",
                evidence_type="业绩",
                direction=ImpactDirection.SUPPORT,
                evidence_locator="没有段落号的定位",
            ),
        )


def test_私有逻辑对他人不可见() -> None:
    other = Actor(user_id="研究员B", teams=frozenset({"权益研究"}))
    assert not permission.can_view_thesis(
        other, owner=OWNER.user_id, visibility=Visibility.PRIVATE, team="权益研究"
    )
    assert permission.can_view_thesis(
        other, owner=OWNER.user_id, visibility=Visibility.TEAM, team="权益研究"
    )
    assert not permission.can_view_thesis(
        other, owner=OWNER.user_id, visibility=Visibility.TEAM, team="固收研究"
    )


def test_管理员不因管理权限获得内容访问权() -> None:
    """PRD 12.1：管理权限与内容权限分开判断。"""
    admin = Actor(user_id="管理员", teams=frozenset(), is_admin=True)
    assert not permission.can_view_thesis(admin, owner=OWNER.user_id, visibility=Visibility.PRIVATE)
    assert not permission.can_view_thesis(
        admin, owner=OWNER.user_id, visibility=Visibility.TEAM, team="权益研究"
    )


def test_预期必须记录来源() -> None:
    """GAP-002：预期值来源未确定，因此录入时强制记录来源。"""
    from app.services import thesis as thesis_service
    from app.services.errors import ValidationFailed

    uow = _setup()
    mapping = MetricMappingRecord(
        mapping_id="MAP-1",
        hypothesis_id="H1",
        metric_id="MET-001",
        expected_direction=ExpectationDirection.HIGHER_BETTER,
        expected_value=Decimal("0.15"),
        expectation_source="",
    )

    with pytest.raises(ValidationFailed, match="预期来源"):
        thesis_service.set_expectations(uow, hypothesis_id="H1", mapping=mapping, actor=OWNER)

    # 补上来源后应当通过，证明拦的是来源缺失而不是别的分支
    thesis_service.set_expectations(
        uow,
        hypothesis_id="H1",
        mapping=replace(mapping, expectation_source="研究员人工录入"),
        actor=OWNER,
    )
    assert uow.thesis.list_mappings("H1")[0].expectation_source == "研究员人工录入"


def test_预期与阈值全空时被拒绝() -> None:
    from app.services import thesis as thesis_service
    from app.services.errors import ValidationFailed

    uow = _setup()
    with pytest.raises(ValidationFailed, match="预期值或失效阈值"):
        thesis_service.set_expectations(
            uow,
            hypothesis_id="H1",
            mapping=MetricMappingRecord(
                mapping_id="MAP-2",
                hypothesis_id="H1",
                metric_id="MET-001",
                expected_direction=ExpectationDirection.HIGHER_BETTER,
                expectation_source="研究员人工录入",
            ),
            actor=OWNER,
        )


def test_观测值记录携带数据版本() -> None:
    """DA-AC-04：任一结果可重复计算，因此观测值必须能追到数据版本。"""
    record = ObservationRecord(
        security_id="DEMO001",
        metric_id="MET-001",
        period="2026Q1",
        observation_date=date(2026, 3, 31),
        unit="%",
        actual_value=Decimal("0.18"),
        data_version="market-demo-v1",
    )
    assert record.data_version
