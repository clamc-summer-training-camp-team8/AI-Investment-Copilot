from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from app.ai.agent import (
    AgentEvent,
    CandidateHypothesis,
    EvidenceAgent,
    InvestmentLogicChangeAgent,
    ThesisDraftAgent,
)
from app.ai.gateway import Gateway
from app.ai.retrieval import KeywordRetriever, RetrievalDocument
from app.core.config import Settings
from app.core.enums import AiStatus


def test_agent_编排检索和事件影响分析() -> None:
    retriever = KeywordRetriever()
    retriever.add(
        [
            RetrievalDocument(
                document_id="history-001",
                security_id="000538.SZ",
                locator="history-001#paragraph-1",
                content="历史公告显示核心业务收入保持增长。",
                published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                source="cninfo",
            )
        ]
    )
    agent = InvestmentLogicChangeAgent(
        gateway=Gateway.build(Settings(llm_provider="mock")),
        retriever=retriever,
    )

    result = agent.analyze(
        AgentEvent(
            event_id="event-001",
            document_id="new-001",
            security_id="000538.SZ",
            segment_locator="new-001#paragraph-1",
            segment_text="公司收入增长。",
            disclosure_time=datetime(2026, 8, 10, tzinfo=timezone.utc),
        ),
        [
            CandidateHypothesis(
                thesis_id="THESIS-001",
                hypothesis_id="THESIS-001-H1",
                statement="核心业务收入保持增长",
            )
        ],
    )

    assert len(result.impacts) == 1
    impact = result.impacts[0]
    assert impact.outcome.ai_status is AiStatus.CANDIDATE
    assert impact.retrieval.items[0].locator == "history-001#paragraph-1"
    assert impact.outcome.payload["hypothesis_id"] == "THESIS-001-H1"


def test_agent_不把未来文档放入上下文() -> None:
    retriever = KeywordRetriever()
    retriever.add(
        [
            RetrievalDocument(
                document_id="future-001",
                security_id="000538.SZ",
                locator="future-001#paragraph-1",
                content="未来收入增长。",
                published_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
            )
        ]
    )
    agent = InvestmentLogicChangeAgent(
        gateway=Gateway.build(Settings(llm_provider="mock")),
        retriever=retriever,
    )

    result = agent.analyze(
        AgentEvent(
            event_id="event-001",
            document_id="new-001",
            security_id="000538.SZ",
            segment_locator="new-001#paragraph-1",
            segment_text="公司收入增长。",
            disclosure_time=datetime(2026, 8, 10, tzinfo=timezone.utc),
        ),
        [CandidateHypothesis("THESIS-001", "H1", "收入保持增长")],
    )

    assert result.impacts[0].retrieval.items == []


def test_thesis_draft_agent_从资料生成初始草稿() -> None:
    retriever = KeywordRetriever()
    agent = ThesisDraftAgent(
        gateway=Gateway.build(Settings(llm_provider="mock")),
        retriever=retriever,
    )
    result = agent.generate(
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

    assert result.retrieval.items[0].locator == "doc-001#paragraph-1"
    assert result.outcome.usable
    assert result.outcome.payload["source_document_id"] == "doc-001"
    assert len(result.outcome.payload["hypotheses"]) >= 2

def test_evidence_agent_拒绝检索结果之外的引用() -> None:
    retriever = KeywordRetriever()
    retriever.add(
        [
            RetrievalDocument(
                document_id="doc-001",
                security_id="000538.SZ",
                locator="doc-001#paragraph-1",
                content="收入增长。",
                published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )
        ]
    )
    result = InvestmentLogicChangeAgent(
        gateway=Gateway.build(Settings(llm_provider="mock")),
        retriever=retriever,
    ).analyze(
        AgentEvent(
            event_id="event-001",
            document_id="new-001",
            security_id="000538.SZ",
            segment_locator="new-001#paragraph-1",
            segment_text="收入增长。",
            disclosure_time=datetime(2026, 8, 10, tzinfo=timezone.utc),
        ),
        [CandidateHypothesis("THESIS-001", "H1", "收入增长")],
    )
    impact = result.impacts[0]
    impact.outcome.payload["citations"] = [{"locator": "unknown#paragraph-9"}]

    check = EvidenceAgent.validate_impact(impact)

    assert not check.valid
    assert check.missing_locators == ("unknown#paragraph-9",)
    assert check.requires_human_review

def test_evidence_agent_计算引用完整性评分() -> None:
    retriever = KeywordRetriever()
    retriever.add(
        [
            RetrievalDocument(
                document_id="history-001",
                security_id="000538.SZ",
                locator="history-001#paragraph-1",
                content="历史公告显示收入增长。",
                published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                source="cninfo",
            )
        ]
    )
    result = InvestmentLogicChangeAgent(
        gateway=Gateway.build(Settings(llm_provider="mock")),
        retriever=retriever,
    ).analyze(
        AgentEvent(
            event_id="event-001",
            document_id="new-001",
            security_id="000538.SZ",
            segment_locator="new-001#paragraph-1",
            segment_text="收入增长。",
            disclosure_time=datetime(2026, 8, 10, tzinfo=timezone.utc),
        ),
        [CandidateHypothesis("THESIS-001", "H1", "收入增长")],
    )
    impact = result.impacts[0]
    impact.outcome.payload["citations"] = [{"locator": "history-001#paragraph-1"}]

    grade = EvidenceAgent.grade_impact(impact)

    assert grade.passed
    assert grade.score == 0.9
    assert grade.valid_cited_count == 2
    assert grade.source_count == 1

def test_evidence_agent_检查事实与引用一致性和实体匹配() -> None:
    retriever = KeywordRetriever()
    retriever.add(
        [
            RetrievalDocument(
                document_id="history-001",
                security_id="000538.SZ",
                locator="history-001#paragraph-1",
                content="历史公告显示收入增长。",
                published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                source="cninfo",
            )
        ]
    )
    result = InvestmentLogicChangeAgent(
        gateway=Gateway.build(Settings(llm_provider="mock")),
        retriever=retriever,
    ).analyze(
        AgentEvent("event-001", "new-001", "000538.SZ", "new-001#paragraph-1", "收入增长。", datetime(2026, 8, 10, tzinfo=timezone.utc)),
        [CandidateHypothesis("THESIS-001", "H1", "收入增长")],
    )
    impact = result.impacts[0]
    impact.outcome.payload["event"]["fact"] = "另一家公司完全无关的事实"

    consistency = EvidenceAgent.check_consistency(impact)

    assert consistency.entity_matched
    assert not consistency.fact_supported
    assert "fact_not_supported" in consistency.reasons