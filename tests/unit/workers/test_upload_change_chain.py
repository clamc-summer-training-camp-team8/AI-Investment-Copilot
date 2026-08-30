from __future__ import annotations

from datetime import date, datetime

from app.ai.gateway import Gateway
from app.ai.graph_rag import RankStableGraphAssistRetriever
from app.ai.retrieval import KeywordRetriever
from app.ai.runtime import InvestmentResearchAgent
from app.core.config import RuleThresholds, Settings
from app.core.domain import (
    AssetSearchHitRecord,
    EventRecord,
    HypothesisRecord,
    SecurityRecord,
    ThesisRecord,
)
from app.core.enums import Importance, ThesisStatus
from app.ingest.events import extract_events_from_segments
from app.services.permission import Actor
from app.workers.change_chain import process_events
from tests.fakes import build_fake_uow


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
        [("DOC-UPLOAD-1#paragraph-1", "公司披露新签订单金额同比增长35%，收入展望改善。")],
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
        document_id="DOC-UPLOAD-1",
        document_title="新公司订单公告",
    )

    assert result.matched_theses == ["THS-NEW001"]
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.security_id == "NEW001"
    assert candidate.source_document_title == "新公司订单公告"
    assert candidate.retrieval_trace is not None
    assert candidate.retrieval_trace["available"] is True
    assert candidate.retrieval_trace["retrieval_mode"] == "text"
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
                visibility_label="内部",
                rank=0.8,
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
        actor=Actor(user_id="researcher-1"),
        thresholds=settings.rules,
        document_id="DOC-RAG",
        document_title="订单公告",
        rag_settings=settings,
    )

    assert len(result.candidates) == 1
    assert captured["visibility_labels"] == ("公开", "内部")
    assert captured["security_ids"] == ("NEW001",)
    assert captured["published_to"] == disclosed_at
    audits = uow.audit.list_for_object("event", events[0].event_id)
    assert any(item.action == "RAG事件假设召回" for item in audits)


def test_event_rag_pilot_is_off_by_default() -> None:
    settings = Settings(_env_file=None, llm_provider="local")
    assert settings.rag_event_pilot_enabled is False
    assert settings.rag_event_pilot_sample_rate == 0.05
    assert settings.rag_graph_enabled is False


def test_graph_rag_显式开启后包装现有_runtime_retriever() -> None:
    uow = build_fake_uow()
    uow.securities.add(SecurityRecord(security_id="NEW001", name="新能源公司"))
    uow.thesis.add(
        ThesisRecord(
            thesis_id="THS-GRAPH",
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
            hypothesis_id="THS-GRAPH-H1",
            thesis_id="THS-GRAPH",
            statement="新签订单增长支撑营业收入提升",
            hypothesis_type="经营",
            importance=Importance.CORE,
        )
    )
    disclosed_at = datetime.fromisoformat("2026-08-12T09:00:00+08:00")
    events = extract_events_from_segments(
        "DOC-GRAPH",
        "NEW001",
        [("DOC-GRAPH#paragraph-1", "公司披露新签订单同比增长35%。")],
        disclosure_time=disclosed_at,
    )
    settings = Settings(_env_file=None, llm_provider="local", rag_graph_enabled=True)
    runtime = InvestmentResearchAgent.build(Gateway.build(settings), retriever=KeywordRetriever())

    result = process_events(
        uow,
        runtime,
        events=events,
        security_id="NEW001",
        actor=Actor(user_id="researcher-1"),
        thresholds=settings.rules,
        document_id="DOC-GRAPH",
        rag_settings=settings,
    )

    assert isinstance(runtime.logic_change.retriever, RankStableGraphAssistRetriever)
    assert len(result.candidates) == 1
    trace = result.candidates[0].retrieval_trace
    assert trace is not None
    assert trace["retrieval_mode"] == "graph_assist"
    assert "investment-graph-rag-v2-layered" in str(trace["retrieval_version"])
    snapshot = trace["graph_snapshot"]
    assert isinstance(snapshot, dict)
    assert str(snapshot["snapshot_id"]).startswith("graph-snapshot:")

    process_events(
        uow,
        runtime,
        events=events,
        security_id="NEW001",
        actor=Actor(user_id="researcher-1"),
        thresholds=settings.rules,
        document_id="DOC-GRAPH",
        rag_settings=settings,
    )
    assert isinstance(runtime.logic_change.retriever, RankStableGraphAssistRetriever)
    assert not isinstance(
        runtime.logic_change.retriever.text_retriever,
        RankStableGraphAssistRetriever,
    )


def test_graph_rag_为公司唯一逻辑记录图画像与排序审计() -> None:
    uow = build_fake_uow()
    uow.securities.add(SecurityRecord(security_id="NEW001", name="新能源公司"))
    uow.thesis.add(
        ThesisRecord(
            thesis_id="THS-COMPANY",
            security_id="NEW001",
            title="公司级投资逻辑",
            direction="观察",
            core_view="订单增长支撑收入，成本下降改善利润率",
            established_on=date(2026, 1, 1),
            owner="researcher-1",
            status=ThesisStatus.VALIDATING,
        )
    )
    for hypothesis_id, statement, title in (
        ("H-ORDER", "订单金额持续增长", "订单验证"),
        ("H-MARGIN", "毛利率保持稳定", "毛利率验证"),
    ):
        uow.thesis.add_hypothesis(
            HypothesisRecord(
                hypothesis_id=hypothesis_id,
                thesis_id="THS-COMPANY",
                statement=statement,
                hypothesis_type="经营",
                importance=Importance.CORE,
                name=title,
            )
        )
    disclosed_at = datetime.fromisoformat("2026-08-12T09:00:00+08:00")
    events = extract_events_from_segments(
        "DOC-RANK",
        "NEW001",
        [("DOC-RANK#paragraph-1", "公司披露新签订单金额增长，订单需求改善。")],
        disclosure_time=disclosed_at,
    )
    settings = Settings(_env_file=None, llm_provider="local", rag_graph_enabled=True)

    result = process_events(
        uow,
        Gateway.build(settings),
        events=events,
        security_id="NEW001",
        actor=Actor(user_id="researcher-1"),
        thresholds=settings.rules,
        document_id="DOC-RANK",
        rag_settings=settings,
    )

    assert result.matched_theses == ["THS-COMPANY"]
    assert result.retrieval_mode == "graph"
    assert len(result.recall_traces) == 1
    assert result.recall_traces[0].graph_score > 0
    audits = uow.audit.list_for_object("event", events[0].event_id)
    ranking = next(item for item in audits if item.action == "RAG候选逻辑排序")
    assert ranking.detail is not None
    assert ranking.detail["graph_snapshot_id"] == result.graph_snapshot_id
