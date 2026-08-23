from __future__ import annotations

from datetime import UTC, datetime

from app.ai.agent import (
    AgentEventInput,
    HypothesisInput,
    InvestmentLogicChangeAgent,
    ThesisDraftAgent,
)
from app.ai.gateway import Gateway
from app.ai.retrieval import KeywordRetriever, RetrievalDocument
from app.ai.runtime import InvestmentResearchAgent
from app.core.config import Settings


def _runtime() -> InvestmentResearchAgent:
    retriever = KeywordRetriever()
    gateway = Gateway.build(Settings(_env_file=None, llm_provider="mock"))
    return InvestmentResearchAgent(
        thesis_draft=ThesisDraftAgent(gateway=gateway, retriever=retriever),
        logic_change=InvestmentLogicChangeAgent(gateway=gateway, retriever=retriever),
    )


def test_runtime_统一编排_thesis_draft_并记录完成状态() -> None:
    runtime = _runtime()
    execution = runtime.draft_thesis(
        security_id="000538.SZ",
        source_document_id="doc-001",
        source_segments=[
            RetrievalDocument(
                document_id="doc-001",
                security_id="000538.SZ",
                locator="doc-001#paragraph-1",
                content="公司收入增长，订单持续提升。",
                published_at=datetime(2026, 8, 1, tzinfo=UTC),
            )
        ],
    )

    assert execution.task == "thesis_draft"
    assert execution.status == "completed"
    assert execution.finished_at is not None
    assert execution.result.outcome.usable
    assert execution.model_version == "local-rule-v1"
    assert execution.prompt_version
    assert execution.retrieval_versions == ("keyword-v1",)


def test_runtime_事件分析完成后进入人工复核状态() -> None:
    runtime = _runtime()
    execution = runtime.analyze_event(
        AgentEventInput(
            event_id="event-001",
            document_id="doc-001",
            security_id="000538.SZ",
            evidence_locator="doc-001#paragraph-1",
            fact="公司收入增长。",
            disclosure_time=datetime(2026, 8, 10, tzinfo=UTC),
            event_type="其他",
        ),
        HypothesisInput("THESIS-001", "H1", "收入增长"),
    )

    assert execution.task == "event_impact"
    assert execution.status == "needs_human_review"
    assert len(execution.evidence_checks) == 1
    assert len(execution.evidence_grades) == 1
    assert execution.evidence_grades[0].score >= 0


def test_runtime_event_analysis_accepts_one_hypothesis() -> None:
    runtime = _runtime()
    execution = runtime.analyze_event(
        AgentEventInput(
            event_id="event-001",
            document_id="doc-001",
            security_id="000538.SZ",
            evidence_locator="doc-001#paragraph-1",
            fact="公司收入增长。",
            disclosure_time=datetime(2026, 8, 10, tzinfo=UTC),
            event_type="其他",
        ),
        HypothesisInput("THESIS-001", "H1", "收入增长"),
    )

    assert execution.status == "needs_human_review"
    assert len(execution.result.impacts) == 1
    assert execution.finished_at is not None


def test_runtime_records_transitions_usage_and_stable_idempotent_run_id() -> None:
    first = _runtime().draft_thesis(
        security_id="000538.SZ",
        view="收入增长",
        idempotency_key="document-DOC-001",
        attempt=2,
    )
    second = _runtime().draft_thesis(
        security_id="000538.SZ",
        view="收入增长",
        idempotency_key="document-DOC-001",
        attempt=2,
    )

    assert first.run_id == second.run_id
    assert first.attempt == 2
    assert [item.status for item in first.transitions] == [
        "created",
        "retrieving",
        "generating",
        "completed",
    ]
    assert len(first.model_calls) == 1
    assert first.model_calls[0].provider == "mock"
