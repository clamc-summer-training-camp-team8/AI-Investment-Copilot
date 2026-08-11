"""投资逻辑变化 Agent 的最小编排器。

Agent 只编排检索和 AI 候选分析，不写数据库、不发布 Thesis、不改变正式状态。
后端可以把 `AgentRunResult.impacts` 转换为候选 Evidence 和 StatusSuggestion。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.ai.gateway import Gateway
from app.ai.retrieval import (
    RetrievedChunk,
    RetrievalDocument,
    RetrievalQuery,
    RetrievalResult,
    Retriever,
)
from app.ai.contracts.validator import ValidationOutcome


@dataclass(frozen=True)
class AgentEvent:
    event_id: str
    document_id: str
    security_id: str
    segment_locator: str
    segment_text: str
    disclosure_time: datetime
    event_type: str = "其他"
    occurred_on: date | None = None


@dataclass(frozen=True)
class CandidateHypothesis:
    thesis_id: str
    hypothesis_id: str
    statement: str


@dataclass(frozen=True)
class AgentImpact:
    candidate: CandidateHypothesis
    retrieval: RetrievalResult
    outcome: ValidationOutcome


@dataclass(frozen=True)
class AgentRunResult:
    event_id: str
    impacts: list[AgentImpact]


@dataclass(frozen=True)
class ThesisDraftRunResult:
    security_id: str
    retrieval: RetrievalResult
    outcome: ValidationOutcome


class ThesisDraftAgent:
    """用观点和/或资料编排初始 Thesis 草稿；不写库、不发布正式 Thesis。"""

    def __init__(self, *, gateway: Gateway, retriever: Retriever) -> None:
        self.gateway = gateway
        self.retriever = retriever

    def generate(
        self,
        *,
        security_id: str,
        view: str = "",
        source_document_id: str | None = None,
        source_segments: list[RetrievalDocument] | None = None,
        as_of: datetime | None = None,
        allowed_visibility: frozenset[str] = frozenset({"公开"}),
        top_k: int = 8,
    ) -> ThesisDraftRunResult:
        """先检索资料，再把带 locator 的片段传给 Gateway。"""
        if source_segments:
            self.retriever.add(source_segments)
        query_text = view or " ".join(
            document.content for document in (source_segments or [])
        )
        retrieval = self.retriever.search(
            RetrievalQuery(
                text=query_text,
                security_id=security_id,
                as_of=as_of,
                allowed_visibility=allowed_visibility,
                top_k=top_k,
            )
        )
        segments = [(item.locator, item.content) for item in retrieval.items]
        if not segments and source_segments:
            segments = [(item.locator, item.content) for item in source_segments[:top_k]]
        outcome = self.gateway.thesis_draft(
            security_id=security_id,
            view=view,
            segments=segments,
            source_document_id=source_document_id,
        )
        return ThesisDraftRunResult(
            security_id=security_id,
            retrieval=retrieval,
            outcome=outcome,
        )

class InvestmentLogicChangeAgent:
    """把新事件编排为一组面向具体假设的候选影响结果。"""

    def __init__(self, *, gateway: Gateway, retriever: Retriever) -> None:
        self.gateway = gateway
        self.retriever = retriever

    @staticmethod
    def _context(candidate: CandidateHypothesis, chunks: list[RetrievedChunk]) -> str:
        lines = [f"目标假设：{candidate.statement}"]
        lines.extend(f"{chunk.locator}: {chunk.content}" for chunk in chunks)
        return "\n".join(lines)

    def analyze(
        self,
        event: AgentEvent,
        candidates: list[CandidateHypothesis],
        *,
        allowed_visibility: frozenset[str] = frozenset({"公开"}),
        top_k: int = 3,
    ) -> AgentRunResult:
        impacts: list[AgentImpact] = []
        for candidate in candidates:
            retrieval = self.retriever.search(
                RetrievalQuery(
                    text=f"{event.segment_text} {candidate.statement}",
                    security_id=event.security_id,
                    as_of=event.disclosure_time,
                    allowed_visibility=allowed_visibility,
                    top_k=top_k,
                )
            )
            outcome = self.gateway.event_impact(
                document_id=event.document_id,
                security_id=event.security_id,
                segment_locator=event.segment_locator,
                segment_text=event.segment_text,
                disclosure_time=event.disclosure_time.isoformat(),
                thesis_id=candidate.thesis_id,
                hypothesis_id=candidate.hypothesis_id,
                event_type=event.event_type,
                occurred_on=event.occurred_on.isoformat() if event.occurred_on else None,
                context=self._context(candidate, retrieval.items),
            )
            impacts.append(AgentImpact(candidate, retrieval, outcome))
        return AgentRunResult(event_id=event.event_id, impacts=impacts)
