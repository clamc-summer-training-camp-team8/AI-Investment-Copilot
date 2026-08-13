"""新事件对既有投资假设的影响分析能力。"""

from __future__ import annotations

from app.ai.agents.evidence import EvidenceAgent
from app.ai.agents.types import (
    AgentEvent,
    AgentImpact,
    AgentRunResult,
    CandidateHypothesis,
    EvidenceValidation,
)
from app.ai.gateway import Gateway
from app.ai.retrieval import RetrievalQuery, RetrievalResult, RetrievedChunk, Retriever


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

            def request_impact(
                repair_errors: list[str] | None = None,
                *,
                active_candidate: CandidateHypothesis = candidate,
                active_retrieval: RetrievalResult = retrieval,
            ):
                return self.gateway.event_impact(
                    document_id=event.document_id,
                    security_id=event.security_id,
                    segment_locator=event.segment_locator,
                    segment_text=event.segment_text,
                    disclosure_time=event.disclosure_time.isoformat(),
                    thesis_id=active_candidate.thesis_id,
                    hypothesis_id=active_candidate.hypothesis_id,
                    thesis_context=(active_candidate.thesis_context or active_candidate.statement),
                    hypothesis_context={
                        **(active_candidate.hypothesis_context or {}),
                        "thesis_id": active_candidate.thesis_id,
                        "hypothesis_id": active_candidate.hypothesis_id,
                        "statement": active_candidate.statement,
                        "retrieved_locators": [item.locator for item in active_retrieval.items],
                    },
                    event_type=event.event_type,
                    occurred_on=(event.occurred_on.isoformat() if event.occurred_on else None),
                    context=self._context(active_candidate, active_retrieval.items),
                    repair_errors=repair_errors,
                )

            outcome = request_impact()
            impact = AgentImpact(candidate, retrieval, outcome)
            validation = EvidenceAgent.validate_impact(impact)
            if outcome.usable and not validation.valid:
                outcome = request_impact(_citation_repair_errors(validation))
                impact = AgentImpact(candidate, retrieval, outcome)
            impacts.append(impact)
        return AgentRunResult(event_id=event.event_id, impacts=impacts)


def _citation_repair_errors(validation: EvidenceValidation) -> list[str]:
    """把证据校验失败转换为模型可执行、但不泄露额外数据的修复要求。"""
    missing = validation.missing_locators
    unsupported = validation.unsupported_claims
    errors: list[str] = []
    if missing:
        errors.append(f"引用不存在或不在允许范围内: {', '.join(missing)}")
    if unsupported:
        errors.append("删除或明确标注 unsupported_claims 中没有证据支持的陈述")
    return errors or ["补全有效引用，且不要新增输入之外的事实"]
