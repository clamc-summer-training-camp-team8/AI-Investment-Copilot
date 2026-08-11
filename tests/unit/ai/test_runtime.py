from __future__ import annotations

from datetime import datetime, timezone

from app.ai.agent import AgentEvent, CandidateHypothesis, InvestmentLogicChangeAgent, ThesisDraftAgent
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
                published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
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
        AgentEvent(
            event_id="event-001",
            document_id="doc-001",
            security_id="000538.SZ",
            segment_locator="doc-001#paragraph-1",
            segment_text="公司收入增长。",
            disclosure_time=datetime(2026, 8, 10, tzinfo=timezone.utc),
        ),
        [CandidateHypothesis("THESIS-001", "H1", "收入增长")],
    )

    assert execution.task == "event_impact"
    assert execution.status == "needs_human_review"
    assert len(execution.evidence_checks) == 1
    assert len(execution.evidence_grades) == 1
    assert execution.evidence_grades[0].score >= 0


def test_runtime_no_candidates_returns_degraded_instead_of_completed() -> None:
    runtime = _runtime()
    execution = runtime.analyze_event(
        AgentEvent(
            event_id="event-001",
            document_id="doc-001",
            security_id="000538.SZ",
            segment_locator="doc-001#paragraph-1",
            segment_text="公司收入增长。",
            disclosure_time=datetime(2026, 8, 10, tzinfo=timezone.utc),
        ),
        [],
    )

    assert execution.status == "degraded"
    assert execution.degraded_reason == "no_candidate_hypotheses"
    assert execution.finished_at is not None