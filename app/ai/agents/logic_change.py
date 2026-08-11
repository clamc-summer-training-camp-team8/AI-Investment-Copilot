"""新事件对既有投资假设的影响分析能力。"""

from __future__ import annotations

from app.ai.agents.types import (
    AgentEvent,
    AgentImpact,
    AgentRunResult,
    CandidateHypothesis,
)
from app.ai.gateway import Gateway
from app.ai.retrieval import RetrievedChunk, RetrievalQuery, Retriever


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
