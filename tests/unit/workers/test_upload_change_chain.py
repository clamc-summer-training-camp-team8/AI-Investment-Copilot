from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.ai.agents import MetricRuleInput
from app.ai.gateway import Gateway
from app.ai.providers.local import LocalProvider
from app.core.config import RuleThresholds, Settings
from app.core.domain import (
    AssetSearchHitRecord,
    DocumentSegmentRecord,
    EventRecord,
    HypothesisRecord,
    MetricMappingRecord,
    SecurityRecord,
    ThesisRecord,
)
from app.core.enums import ExpectationDirection, Importance, ThesisStatus
from app.ingest.events import ExtractedEvent, extract_events_from_segments
from app.services.permission import Actor
from app.workers.agent_input import build_hypothesis_input
from app.workers.change_chain import process_events
from tests.fakes import build_fake_uow


class _CountingLocalProvider(LocalProvider):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.event_calls = 0
        self.batch_calls = 0
        self.calls: list[dict[str, Any]] = []

    def analyze_event_impact(self, **kwargs: Any) -> dict[str, Any]:
        self.event_calls += 1
        self.calls.append(kwargs)
        return super().analyze_event_impact(**kwargs)

    def analyze_event_impacts(self, **kwargs: Any) -> dict[str, Any]:
        self.batch_calls += 1
        return super().analyze_event_impacts(**kwargs)


class _PerHypothesisProvider(_CountingLocalProvider):
    def __init__(self, settings: Settings, directions: dict[str, str]) -> None:
        super().__init__(settings)
        self.directions = directions

    def analyze_event_impact(self, **kwargs: Any) -> dict[str, Any]:
        payload = super().analyze_event_impact(**kwargs)
        for impact in payload["impacts"]:
            impact["signal"]["impact_direction"] = self.directions[str(impact["hypothesis_id"])]
            if impact["signal"]["impact_direction"] == "无关":
                impact["relevance"] = "不相关"
        return payload


def test_uploaded_event_becomes_radar_visible_candidate_relation() -> None:
    uow = build_fake_uow()
    uow.securities.add(SecurityRecord(security_id="NEW001", name="新能源公司"))
    uow.thesis.add(
        ThesisRecord(
            thesis_id="THS-NEW001",
            security_id="NEW001",
            title="订单验证",
            direction="观察",
            core_view="订单增长将支撑收入",
            established_on=date(2026, 1, 1),
            owner="researcher-1",
            status=ThesisStatus.VALIDATING,
        )
    )
    uow.thesis.add_hypothesis(
        HypothesisRecord(
            hypothesis_id="THS-NEW001-H1",
            thesis_id="THS-NEW001",
            statement="新签订单增长支撑营业收入提升",
            hypothesis_type="经营",
            importance=Importance.CORE,
        )
    )
    disclosed_at = datetime.fromisoformat("2026-08-12T09:00:00+08:00")
    events = extract_events_from_segments(
        "DOC-UPLOAD-1",
        "NEW001",
        [
            (
                "DOC-UPLOAD-1#paragraph-1",
                "公司披露新签订单金额同比增长35%，收入展望改善。",
            )
        ],
        disclosure_time=disclosed_at,
    )
    for event in events:
        uow.events.add(
            EventRecord(
                event_id=event.event_id,
                document_id=event.document_id,
                security_id=event.security_id,
                event_type=event.event_type,
                summary=event.summary,
                disclosure_time=event.disclosure_time,
                fingerprint=event.fingerprint,
                source_document_ids=[event.document_id],
            )
        )

    result = process_events(
        uow,
        Gateway.build(Settings(_env_file=None, llm_provider="local")),
        events=events,
        security_id="NEW001",
        actor=Actor(user_id="researcher-1"),
        thresholds=RuleThresholds(),
        current_event_segments=[
            DocumentSegmentRecord(
                document_id="DOC-UPLOAD-1",
                locator="DOC-UPLOAD-1#paragraph-1",
                ordinal=1,
                content="公司披露新签订单金额同比增长35%，收入展望改善。",
            )
        ],
        document_id="DOC-UPLOAD-1",
        document_title="新公司订单公告",
    )

    assert result.matched_theses == ["THS-NEW001"]
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.security_id == "NEW001"
    assert candidate.source_document_title == "新公司订单公告"
    relations = uow.relations.list_for_evidence(candidate.evidence_id)
    assert len(relations) == 1
    assert relations[0].thesis_id == "THS-NEW001"


def test_document_title_is_not_extracted_as_duplicate_event() -> None:
    disclosed_at = datetime.fromisoformat("2026-08-12T09:00:00+08:00")
    events = extract_events_from_segments(
        "DOC-UPLOAD-2",
        "NEW001",
        [
            ("DOC-UPLOAD-2#paragraph-1", "新能源公司订单公告"),
            ("DOC-UPLOAD-2#paragraph-2", "公司披露新签订单金额同比增长35%。"),
        ],
        disclosure_time=disclosed_at,
    )

    assert len(events) == 1
    assert events[0].evidence_locator == "DOC-UPLOAD-2#paragraph-2"


def test_event_rag_pilot_is_explicit_sampled_permission_filtered_context() -> None:
    uow = build_fake_uow()
    uow.securities.add(SecurityRecord(security_id="NEW001", name="新能源公司"))
    uow.thesis.add(
        ThesisRecord(
            thesis_id="THS-RAG",
            security_id="NEW001",
            title="订单验证",
            direction="观察",
            core_view="订单增长将支撑收入",
            established_on=date(2026, 1, 1),
            owner="researcher-1",
            status=ThesisStatus.VALIDATING,
        )
    )
    uow.thesis.add_hypothesis(
        HypothesisRecord(
            hypothesis_id="THS-RAG-H1",
            thesis_id="THS-RAG",
            statement="新签订单增长支撑营业收入提升",
            hypothesis_type="经营",
            importance=Importance.CORE,
        )
    )
    disclosed_at = datetime.fromisoformat("2026-08-12T09:00:00+08:00")
    events = extract_events_from_segments(
        "DOC-RAG",
        "NEW001",
        [("DOC-RAG#paragraph-1", "公司披露新签订单同比增长35%，收入展望改善。")],
        disclosure_time=disclosed_at,
    )
    captured: dict[str, object] = {}

    def search(**kwargs):
        captured.update(kwargs)
        return [
            AssetSearchHitRecord(
                document_id="DOC-HISTORY",
                locator="DOC-HISTORY#paragraph-2",
                content="历史订单验证材料",
                visibility_label="team-a",
                rank=0.8,
                published_at=datetime.fromisoformat("2026-08-01T09:00:00+08:00"),
                source="2026年7月订单跟踪报告",
            )
        ]

    uow.assets.hybrid_search_segments = search  # type: ignore[method-assign]
    settings = Settings(
        _env_file=None,
        llm_provider="local",
        rag_event_pilot_enabled=True,
        rag_event_pilot_sample_rate=1,
    )
    result = process_events(
        uow,
        Gateway.build(settings),
        events=events,
        security_id="NEW001",
        actor=Actor(
            user_id="researcher-1",
            document_labels=frozenset({"公开", "内部", "team-a"}),
        ),
        thresholds=settings.rules,
        current_event_segments=[
            DocumentSegmentRecord(
                document_id="DOC-RAG",
                locator="DOC-RAG#paragraph-1",
                ordinal=1,
                content="公司披露新签订单同比增长35%，收入展望改善。",
            )
        ],
        document_id="DOC-RAG",
        document_title="订单公告",
        rag_settings=settings,
    )

    assert len(result.candidates) == 1
    assert captured["visibility_labels"] == ("team-a", "公开", "内部")
    assert captured["security_ids"] == ("NEW001",)
    assert captured["published_to"] == disclosed_at
    audits = uow.audit.list_for_object("event", events[0].event_id)
    assert any(item.action == "RAG事件假设召回" for item in audits)


def test_event_rag_pilot_is_off_by_default() -> None:
    settings = Settings(_env_file=None, llm_provider="local")
    assert settings.rag_event_pilot_enabled is False
    assert settings.rag_event_pilot_sample_rate == 0.05


def test_worker_analyzes_each_recalled_thesis_hypothesis() -> None:
    uow = build_fake_uow()
    uow.securities.add(SecurityRecord(security_id="NEW001", name="新能源公司"))
    for index in (1, 2):
        thesis_id = f"THS-MULTI-{index}"
        uow.thesis.add(
            ThesisRecord(
                thesis_id=thesis_id,
                security_id="NEW001",
                title=f"订单逻辑 {index}",
                direction="观察",
                core_view="订单增长支撑收入兑现",
                established_on=date(2026, 1, index),
                owner="researcher-1",
                status=ThesisStatus.VALIDATING,
            )
        )
        uow.thesis.add_hypothesis(
            HypothesisRecord(
                hypothesis_id=f"{thesis_id}-H1",
                thesis_id=thesis_id,
                statement="新签订单增长支撑营业收入提升",
                hypothesis_type="经营",
                importance=Importance.CORE,
            )
        )

    disclosed_at = datetime.fromisoformat("2026-08-12T09:00:00+08:00")
    event = ExtractedEvent(
        event_id="EV-MULTI",
        document_id="DOC-MULTI",
        security_id="NEW001",
        event_type="订单",
        summary="公司新签订单同比增长35%",
        disclosure_time=disclosed_at,
        fingerprint="fp-multi",
        evidence_locator="DOC-MULTI#paragraph-1",
    )
    settings = Settings(_env_file=None, llm_provider="local")
    provider = _CountingLocalProvider(settings)

    result = process_events(
        uow,
        Gateway(settings=settings, provider=provider),
        events=[event],
        security_id="NEW001",
        actor=Actor(user_id="researcher-1"),
        thresholds=settings.rules,
        current_event_segments=[
            DocumentSegmentRecord(
                document_id="DOC-MULTI",
                locator="DOC-MULTI#paragraph-1",
                ordinal=1,
                content="公司披露新签订单金额同比增长35%。",
            )
        ],
        document_id="DOC-MULTI",
    )

    assert provider.event_calls == 2
    assert len(result.candidates) == 2
    assert result.matched_theses == ["THS-MULTI-1", "THS-MULTI-2"]


def test_worker_analyzes_multiple_events_in_one_batch_per_thesis() -> None:
    uow = build_fake_uow()
    uow.securities.add(SecurityRecord(security_id="NEW001", name="新能源公司"))
    uow.thesis.add(
        ThesisRecord(
            thesis_id="THS-CONCURRENT",
            security_id="NEW001",
            title="经营数据逻辑",
            direction="观察",
            core_view="销量增长支撑收入",
            established_on=date(2026, 1, 1),
            owner="researcher-1",
            status=ThesisStatus.VALIDATING,
        )
    )
    uow.thesis.add_hypothesis(
        HypothesisRecord(
            hypothesis_id="THS-CONCURRENT-H1",
            thesis_id="THS-CONCURRENT",
            statement="销量增长支撑营业收入提升",
            hypothesis_type="经营",
            importance=Importance.CORE,
        )
    )
    disclosed_at = datetime.fromisoformat("2026-08-12T09:00:00+08:00")
    events = [
        ExtractedEvent(
            event_id=f"EV-CONCURRENT-{index}",
            document_id="DOC-CONCURRENT",
            security_id="NEW001",
            event_type="业绩",
            summary=f"第{index}项销量同比增长",
            disclosure_time=disclosed_at,
            fingerprint=f"fp-concurrent-{index}",
            evidence_locator=f"DOC-CONCURRENT#paragraph-{index}",
        )
        for index in (1, 2)
    ]
    settings = Settings(_env_file=None, llm_provider="local")
    provider = _CountingLocalProvider(settings)

    result = process_events(
        uow,
        Gateway(settings=settings, provider=provider),
        events=events,
        security_id="NEW001",
        actor=Actor(user_id="researcher-1"),
        thresholds=settings.rules,
        current_event_segments=[
            DocumentSegmentRecord(
                document_id="DOC-CONCURRENT",
                locator=f"DOC-CONCURRENT#paragraph-{index}",
                ordinal=index,
                content=f"第{index}项销量同比增长。",
            )
            for index in (1, 2)
        ],
        document_id="DOC-CONCURRENT",
    )

    assert provider.batch_calls == 1
    assert provider.event_calls == 2  # local provider deterministically expands the batch
    assert len(result.candidates) == 2


def test_worker_passes_all_thesis_hypotheses_and_persists_each_related_impact() -> None:
    uow = build_fake_uow()
    uow.securities.add(SecurityRecord(security_id="NEW001", name="新能源公司"))
    thesis_id = "THS-BATCH"
    uow.thesis.add(
        ThesisRecord(
            thesis_id=thesis_id,
            security_id="NEW001",
            title="经营质量逻辑",
            direction="观察",
            core_view="产能利用率与毛利率共同决定经营质量",
            established_on=date(2026, 1, 1),
            owner="researcher-1",
            status=ThesisStatus.VALIDATING,
        )
    )
    hypothesis_specs = (
        ("H1", "产能利用率持续改善"),
        ("H2", "毛利率持续改善"),
        ("H3", "资本开支持续增长"),
    )
    for suffix, statement in hypothesis_specs:
        uow.thesis.add_hypothesis(
            HypothesisRecord(
                hypothesis_id=f"{thesis_id}-{suffix}",
                thesis_id=thesis_id,
                statement=statement,
                hypothesis_type="经营",
                importance=Importance.CORE,
            )
        )
    uow.thesis.add_mapping(
        MetricMappingRecord(
            mapping_id="MAP-CAPACITY",
            hypothesis_id=f"{thesis_id}-H1",
            metric_id="capacity_utilization",
            expected_direction=ExpectationDirection.HIGHER_BETTER,
        )
    )
    uow.thesis.add_mapping(
        MetricMappingRecord(
            mapping_id="MAP-MARGIN",
            hypothesis_id=f"{thesis_id}-H2",
            metric_id="gross_margin",
            expected_direction=ExpectationDirection.HIGHER_BETTER,
        )
    )
    event = ExtractedEvent(
        event_id="EV-BATCH",
        document_id="DOC-BATCH",
        security_id="NEW001",
        event_type="业绩",
        summary="公司Q2产能利用率下降，同时毛利率同比下降",
        disclosure_time=datetime.fromisoformat("2026-08-12T09:00:00+08:00"),
        fingerprint="fp-batch",
        evidence_locator="DOC-BATCH#paragraph-1",
    )
    settings = Settings(_env_file=None, llm_provider="local")
    provider = _PerHypothesisProvider(
        settings,
        {
            f"{thesis_id}-H1": "冲突",
            f"{thesis_id}-H2": "冲突",
            f"{thesis_id}-H3": "无关",
        },
    )

    result = process_events(
        uow,
        Gateway(settings=settings, provider=provider),
        events=[event],
        security_id="NEW001",
        actor=Actor(user_id="researcher-1"),
        thresholds=settings.rules,
        current_event_segments=[
            DocumentSegmentRecord(
                document_id="DOC-BATCH",
                locator="DOC-BATCH#paragraph-1",
                ordinal=1,
                content="财报原文：公司Q2产能利用率下降，同时毛利率同比下降。",
            )
        ],
        document_id="DOC-BATCH",
    )

    assert provider.event_calls == 1
    candidates = provider.calls[0]["candidates"]
    assert [str(candidate["hypothesis_id"]) for candidate in candidates] == [
        f"{thesis_id}-H1",
        f"{thesis_id}-H2",
        f"{thesis_id}-H3",
    ]
    assert [item["metric_id"] for item in candidates[0]["metric_rules"]] == ["capacity_utilization"]
    assert [item["metric_id"] for item in candidates[1]["metric_rules"]] == ["gross_margin"]
    assert candidates[2]["metric_rules"] == []
    assert {candidate.hypothesis_id for candidate in result.candidates} == {
        f"{thesis_id}-H1",
        f"{thesis_id}-H2",
    }
    assert all(candidate.direction.value == "冲突" for candidate in result.candidates)
    assert any("不相关" in reason for _, reason in result.deferred)


def test_worker_does_not_call_agent_when_candidate_list_is_empty() -> None:
    uow = build_fake_uow()
    uow.securities.add(SecurityRecord(security_id="NEW001", name="新能源公司"))
    uow.thesis.add(
        ThesisRecord(
            thesis_id="THS-NO-MATCH",
            security_id="NEW001",
            title="订单逻辑",
            direction="观察",
            core_view="订单增长支撑收入兑现",
            established_on=date(2026, 1, 1),
            owner="researcher-1",
            status=ThesisStatus.VALIDATING,
        )
    )
    event = ExtractedEvent(
        event_id="EV-NO-MATCH",
        document_id="DOC-NO-MATCH",
        security_id="NEW001",
        event_type="治理",
        summary="董事会完成换届",
        disclosure_time=datetime.fromisoformat("2026-08-12T09:00:00+08:00"),
        fingerprint="fp-no-match",
        evidence_locator="DOC-NO-MATCH#paragraph-1",
    )
    settings = Settings(_env_file=None, llm_provider="local")
    provider = _CountingLocalProvider(settings)

    result = process_events(
        uow,
        Gateway(settings=settings, provider=provider),
        events=[event],
        security_id="NEW001",
        actor=Actor(user_id="researcher-1"),
        thresholds=settings.rules,
        current_event_segments=[
            DocumentSegmentRecord(
                document_id="DOC-NO-MATCH",
                locator="DOC-NO-MATCH#paragraph-1",
                ordinal=1,
                content="公司公告董事会完成换届。",
            )
        ],
        document_id="DOC-NO-MATCH",
    )

    assert provider.event_calls == 0
    assert result.candidates == []
    assert result.deferred == [("EV-NO-MATCH", "候选逻辑下没有可分析假设，转人工判断")]


def test_worker_defers_event_when_source_segment_is_missing() -> None:
    uow = build_fake_uow()
    uow.securities.add(SecurityRecord(security_id="NEW001", name="新能源公司"))
    uow.thesis.add(
        ThesisRecord(
            thesis_id="THS-MISSING-SEGMENT",
            security_id="NEW001",
            title="产能逻辑",
            direction="观察",
            core_view="产能利用率支撑收入兑现",
            established_on=date(2026, 1, 1),
            owner="researcher-1",
            status=ThesisStatus.VALIDATING,
        )
    )
    uow.thesis.add_hypothesis(
        HypothesisRecord(
            hypothesis_id="THS-MISSING-SEGMENT-H1",
            thesis_id="THS-MISSING-SEGMENT",
            statement="产能利用率维持高位",
            hypothesis_type="经营",
            importance=Importance.CORE,
        )
    )
    event = ExtractedEvent(
        event_id="EV-MISSING-SEGMENT",
        document_id="DOC-MISSING-SEGMENT",
        security_id="NEW001",
        event_type="经营指标",
        summary="产能利用率下降",
        disclosure_time=datetime.fromisoformat("2026-08-12T09:00:00+08:00"),
        fingerprint="fp-missing-segment",
        evidence_locator="DOC-MISSING-SEGMENT#paragraph-1",
    )
    settings = Settings(_env_file=None, llm_provider="local")
    provider = _CountingLocalProvider(settings)

    result = process_events(
        uow,
        Gateway(settings=settings, provider=provider),
        events=[event],
        security_id="NEW001",
        actor=Actor(user_id="researcher-1"),
        thresholds=settings.rules,
        current_event_segments=[],
        document_id="DOC-MISSING-SEGMENT",
    )

    assert provider.event_calls == 0
    assert result.candidates == []
    assert result.deferred == [("EV-MISSING-SEGMENT", "引用定位无法回查原文，转人工判断")]


def test_worker_maps_metric_rules_to_typed_agent_contract() -> None:
    thesis_record = ThesisRecord(
        thesis_id="THS-METRIC",
        security_id="NEW001",
        title="收入逻辑",
        direction="观察",
        core_view="收入增长支撑盈利改善",
        established_on=date(2026, 1, 1),
        owner="researcher-1",
    )
    hypothesis = HypothesisRecord(
        hypothesis_id="THS-METRIC-H1",
        thesis_id="THS-METRIC",
        statement="营业收入保持增长",
        hypothesis_type="经营",
        importance=Importance.CORE,
        expected_direction=ExpectationDirection.HIGHER_BETTER,
        invalidation_rule="收入同比低于0%",
    )
    mapping = MetricMappingRecord(
        mapping_id="MAP-1",
        hypothesis_id=hypothesis.hypothesis_id,
        metric_id="revenue_yoy",
        expected_direction=ExpectationDirection.HIGHER_BETTER,
        expected_value=Decimal("10"),
        invalidation_threshold=Decimal("0"),
    )

    with_mapping = build_hypothesis_input(
        thesis_record=thesis_record,
        hypothesis=hypothesis,
        mappings=[mapping],
    )
    without_mapping = build_hypothesis_input(
        thesis_record=thesis_record,
        hypothesis=hypothesis,
        mappings=[],
    )

    assert with_mapping.metric_rules == (
        MetricRuleInput(
            metric_id="revenue_yoy",
            expected_direction="越高越好",
            expected_value=Decimal("10"),
            invalidation_threshold=Decimal("0"),
        ),
    )
    assert without_mapping.metric_rules == ()
