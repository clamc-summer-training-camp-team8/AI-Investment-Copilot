from __future__ import annotations

from app.ai.agent import InvestmentLogicChangeAgent, ThesisDraftAgent
from app.ai.gateway import Gateway
from app.ai.real_data import load_real_data, map_direction, map_event_type
from app.ai.retrieval import KeywordRetriever
from app.ai.runtime import InvestmentResearchAgent
from app.core.config import Settings
from app.core.enums import ImpactDirection


def test_real_data_adapter_loads_committed_dataset() -> None:
    bundle = load_real_data()

    assert len(bundle.announcements) == 3784
    assert len(bundle.events) == 3784
    assert len(bundle.theses) == 45
    assert sum(len(thesis.hypotheses) for thesis in bundle.theses) == 135


def test_real_data_adapter_preserves_identity_and_traceability() -> None:
    bundle = load_real_data()
    announcement = bundle.announcements[0]
    event = bundle.events[0].to_agent_event()
    document = announcement.to_retrieval_document()

    assert announcement.security_id.startswith("0")
    assert document.document_id == event.document_id
    assert document.locator == event.evidence_locator
    assert document.content == announcement.title
    assert document.source == "cninfo-title"


def test_real_data_adapter_maps_dataset_direction_vocabulary() -> None:
    assert map_direction("支持") is ImpactDirection.SUPPORT
    assert map_direction("削弱") is ImpactDirection.CONFLICT
    assert map_direction("中性") is ImpactDirection.NEUTRAL
    assert map_direction("无关") is ImpactDirection.IRRELEVANT


def test_real_data_adapter_maps_categories_to_schema_event_types() -> None:
    assert map_event_type("订单与合同") == "订单"
    assert map_event_type("定期报告") == "业绩"
    assert map_event_type("集采与准入") == "政策"
    assert map_event_type("治理") == "其他"


def test_real_dataset_event_runs_through_runtime_contract() -> None:
    bundle = load_real_data()
    event_record = bundle.events[0]
    thesis = next(item for item in bundle.theses if item.security_id == event_record.security_id)
    announcement = next(
        item
        for item in bundle.announcements
        if item.announcement_id == event_record.announcement_id
    )
    retriever = KeywordRetriever()
    retriever.add([announcement.to_retrieval_document()])
    gateway = Gateway.build(Settings(_env_file=None, llm_provider="mock"))
    runtime = InvestmentResearchAgent(
        thesis_draft=ThesisDraftAgent(gateway=gateway, retriever=retriever),
        logic_change=InvestmentLogicChangeAgent(gateway=gateway, retriever=retriever),
    )

    execution = runtime.analyze_event(event_record.to_agent_event(), thesis.hypotheses)

    assert execution.status == "needs_human_review"
    assert len(execution.result.impacts) == len(thesis.hypotheses)
    assert all(impact.outcome.usable for impact in execution.result.impacts)
    assert execution.retrieval_versions == ("keyword-v1",)
