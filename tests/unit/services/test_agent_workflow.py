from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast

from app.ai.gateway import Gateway
from app.ai.runtime import InvestmentResearchAgent
from app.core.config import Settings
from app.core.domain import (
    EvidenceRecord,
    EvidenceRelationRecord,
    HypothesisRecord,
    MetricDefinitionRecord,
    MetricMappingRecord,
    ObservationRecord,
    SecurityRecord,
    ThesisRecord,
)
from app.core.enums import (
    ConfirmationStatus,
    ExpectationDirection,
    ImpactDirection,
    Importance,
    ThesisStatus,
)
from app.services import agent_workflow, version
from app.services.errors import ValidationFailed
from app.services.permission import Actor
from tests.fakes import build_fake_uow


def _settings() -> Settings:
    return Settings(_env_file=None, llm_provider="local", debug=True)


def _runtime(settings: Settings) -> InvestmentResearchAgent:
    return InvestmentResearchAgent.build(Gateway.build(settings))


def _case(*, status: ThesisStatus = ThesisStatus.DRAFT):
    uow = build_fake_uow()
    uow.securities.add(SecurityRecord("002594", "比亚迪", industry="新能源汽车"))
    thesis = ThesisRecord(
        thesis_id="THS-AGENT-1",
        security_id="002594",
        title="新能源汽车需求验证",
        direction="观察",
        core_view="月度销量增长能够验证终端需求",
        established_on=date(2026, 1, 1),
        owner="analyst-mvp",
        status=status,
        version=1 if status is not ThesisStatus.DRAFT else 0,
    )
    hypothesis = HypothesisRecord(
        hypothesis_id="THS-AGENT-1-H1",
        thesis_id=thesis.thesis_id,
        statement="新能源汽车月度销量持续增长",
        hypothesis_type="经营",
        importance=Importance.CORE,
    )
    uow.thesis.add(thesis)
    uow.thesis.add_hypothesis(hypothesis)
    return uow, thesis, hypothesis, Actor(user_id="analyst-mvp")


def test_metric_recommendation_adds_auditable_threshold_without_saving_mapping() -> None:
    uow, thesis, hypothesis, actor = _case()
    for month in range(1, 9):
        uow.observations.add(
            ObservationRecord(
                security_id=thesis.security_id,
                metric_id="AUTO-SALES-M",
                period=f"2025M{month:02d}",
                observation_date=date(2025, month, 28),
                unit="辆",
                actual_value=Decimal(90 + month),
                source_document_id=f"DOC-{month}",
            )
        )

    candidate = agent_workflow.recommend_metrics(
        uow,
        thesis_id=thesis.thesis_id,
        hypothesis_id=hypothesis.hypothesis_id,
        actor=actor,
        settings=_settings(),
        runtime=_runtime(_settings()),
        as_of=date(2026, 1, 1),
    )

    recommendation = next(
        item for item in candidate.payload["recommendations"] if item["metric_id"] == "AUTO-SALES-M"
    )
    threshold = recommendation["threshold_suggestion"]
    assert threshold["method"] == "historical_quantile"
    assert threshold["sample_count"] == 8
    assert threshold["requires_human_review"] is True
    assert uow.thesis.list_mappings(hypothesis.hypothesis_id) == []


def test_database_metric_catalog_uses_observations_for_unknown_industry() -> None:
    uow = build_fake_uow()
    security = SecurityRecord(
        "600519",
        "贵州茅台",
        ticker="600519.SH",
        industry="制造业-酒、饮料和精制茶制造业",
    )
    uow.securities.add(security)
    uow.metrics.items[("FIN-REVENUE-CUM", "v1.0")] = MetricDefinitionRecord(
        metric_id="FIN-REVENUE-CUM",
        version="v1.0",
        name="营业总收入",
        unit="元",
        category="财务与运营",
        definition="报告期累计营业总收入。",
        frequency="随财报",
        period_type="累计",
        source_id="eastmoney-quant-api",
    )
    uow.observations.add(
        ObservationRecord(
            security_id=security.security_id,
            metric_id="FIN-REVENUE-CUM",
            period="2026Q2",
            observation_date=date(2026, 6, 30),
            unit="元",
            actual_value=Decimal("100"),
        )
    )

    catalog = agent_workflow.build_database_metric_catalog(uow, security.security_id)
    candidates = catalog.search(
        hypothesis="需求增长能够传导至公司收入和利润改善",
        security_id=security.security_id,
        industry=security.industry,
        top_k=8,
    )

    assert candidates
    assert candidates[0].metric_id == "FIN-REVENUE-CUM"
    assert candidates[0].source_ids == ("eastmoney-quant-api",)


def test_metric_explanation_only_explains_deterministic_trend() -> None:
    uow, thesis, hypothesis, actor = _case(status=ThesisStatus.VALIDATING)
    uow.thesis.add_mapping(
        MetricMappingRecord(
            mapping_id="MAP-1",
            hypothesis_id=hypothesis.hypothesis_id,
            metric_id="AUTO-SALES-M",
            expected_direction=ExpectationDirection.HIGHER_BETTER,
            expected_value=Decimal("100"),
            invalidation_threshold=Decimal("90"),
            confirmation_status=ConfirmationStatus.CONFIRMED,
        )
    )
    for month, value in enumerate((100, 110, 120, 130), start=1):
        uow.observations.add(
            ObservationRecord(
                security_id=thesis.security_id,
                metric_id="AUTO-SALES-M",
                period=f"2026M{month:02d}",
                observation_date=date(2026, month, 28),
                unit="辆",
                actual_value=Decimal(value),
                expected_value=Decimal("100"),
            )
        )

    candidate = agent_workflow.explain_metric_results(
        uow,
        thesis_id=thesis.thesis_id,
        hypothesis_id=hypothesis.hypothesis_id,
        actor=actor,
        settings=_settings(),
        runtime=_runtime(_settings()),
    )

    assert candidate.task == "metric_explain"
    assert candidate.payload["calculation_source"] == "app.calc"
    assert "上升" in candidate.payload["summary"]


def test_review_draft_uses_confirmed_evidence_in_requested_period() -> None:
    uow, thesis, hypothesis, actor = _case(status=ThesisStatus.VALIDATING)
    evidence = EvidenceRecord(
        evidence_id="EVD-1",
        thesis_id=thesis.thesis_id,
        hypothesis_id=hypothesis.hypothesis_id,
        evidence_type="经营",
        direction=ImpactDirection.SUPPORT,
        evidence_locator="DOC-1#paragraph-1",
        fact_excerpt="公司月度销量同比增长",
        disclosed_at=datetime(2026, 6, 1, tzinfo=UTC),
        confirmation_status=ConfirmationStatus.PENDING,
    )
    uow.evidence.add(evidence)
    uow.relations.add(
        EvidenceRelationRecord(
            relation_id="REL-1",
            evidence_id=evidence.evidence_id,
            thesis_id=thesis.thesis_id,
            hypothesis_id=hypothesis.hypothesis_id,
            direction=ImpactDirection.SUPPORT,
            strength="高",
            status=ConfirmationStatus.CONFIRMED,
            created_by="system",
            reviewed_by=actor.user_id,
        )
    )

    candidate = agent_workflow.draft_review(
        uow,
        thesis_id=thesis.thesis_id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 6, 30),
        actor=actor,
        settings=_settings(),
        runtime=_runtime(_settings()),
    )

    assert candidate.task == "review_draft"
    assert candidate.payload["supporting_changes"] == ["公司月度销量同比增长"]
    assert candidate.payload["citations"] == ["DOC-1#paragraph-1"]
    assert candidate.requires_human_review is True


def test_major_risk_revision_stays_editing_and_keeps_existing_hypothesis_ids() -> None:
    uow, thesis, hypothesis, actor = _case(status=ThesisStatus.MAJOR_RISK)
    version.create(
        uow.versions,
        thesis=thesis,
        hypotheses=[hypothesis],
        triggered_by=version.TRIGGER_STATUS,
        created_by=actor.user_id,
    )

    candidate = agent_workflow.draft_revision(
        uow,
        thesis_id=thesis.thesis_id,
        actor=actor,
        settings=_settings(),
        runtime=_runtime(_settings()),
    )

    assert candidate.revision.status == "editing"
    metadata = cast(dict[str, Any], candidate.revision.payload["ai_revision_candidate"])
    revised = cast(list[dict[str, Any]], candidate.revision.payload["hypotheses"])
    assert metadata["requires_human_review"] is True
    assert [item["hypothesis_id"] for item in revised] == [hypothesis.hypothesis_id]
    stored = uow.thesis.get(thesis.thesis_id)
    assert stored is not None
    assert stored.core_view == thesis.core_view

    try:
        agent_workflow.draft_revision(
            uow,
            thesis_id=thesis.thesis_id,
            actor=actor,
            settings=_settings(),
            runtime=_runtime(_settings()),
        )
    except ValidationFailed as exc:
        assert "避免覆盖人工修改" in str(exc)
    else:
        raise AssertionError("已有修订草稿时不得覆盖")
