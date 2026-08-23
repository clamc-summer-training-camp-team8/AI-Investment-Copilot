"""新事件对既有投资假设的影响分析能力。"""

from __future__ import annotations

from app.ai.agents.evidence import EvidenceAgent
from app.ai.agents.types import (
    AgentEventInput,
    AgentImpact,
    AgentRunResult,
    EvidenceValidation,
    HypothesisInput,
)
from app.ai.gateway import Gateway
from app.ai.retrieval import RetrievalQuery, RetrievalResult, RetrievedChunk, Retriever


class InvestmentLogicChangeAgent:
    """分析一个新事件对一条具体投资假设的候选影响。"""

    def __init__(self, *, gateway: Gateway, retriever: Retriever) -> None:
        self.gateway = gateway
        self.retriever = retriever

    @staticmethod
    def _context(hypothesis: HypothesisInput, chunks: list[RetrievedChunk]) -> str:
        lines = [f"目标假设：{hypothesis.statement}"]
        lines.extend(f"{chunk.locator}: {chunk.content}" for chunk in chunks)
        return "\n".join(lines)

    @staticmethod
    def _hypothesis_context(
        hypothesis: HypothesisInput,
        retrieval: RetrievalResult,
    ) -> dict[str, object]:
        """在 Gateway 边界把 typed contract 转成 Provider 使用的 JSON 结构。"""
        return {
            "thesis_id": hypothesis.thesis_id,
            "hypothesis_id": hypothesis.hypothesis_id,
            "statement": hypothesis.statement,
            "hypothesis_type": hypothesis.hypothesis_type,
            "importance": hypothesis.importance,
            "expected_direction": hypothesis.expected_direction,
            "invalidation_rule": hypothesis.invalidation_rule,
            "metrics": [
                {
                    "metric_id": rule.metric_id,
                    "expected_direction": rule.expected_direction,
                    "expected_value": (
                        str(rule.expected_value) if rule.expected_value is not None else None
                    ),
                    "invalidation_threshold": (
                        str(rule.invalidation_threshold)
                        if rule.invalidation_threshold is not None
                        else None
                    ),
                }
                for rule in hypothesis.metric_rules
            ],
            "retrieved_locators": [item.locator for item in retrieval.items],
        }

    def analyze(
        self,
        event: AgentEventInput,
        hypothesis: HypothesisInput,
        *,
        allowed_visibility: frozenset[str] = frozenset({"公开"}),
        top_k: int = 3,
    ) -> AgentRunResult:
        retrieval = self.retriever.search(
            RetrievalQuery(
                text=f"{event.fact} {hypothesis.statement}",
                security_id=event.security_id,
                as_of=event.disclosure_time,
                allowed_visibility=allowed_visibility,
                top_k=top_k,
            )
        )

        def request_impact(repair_errors: list[str] | None = None):
            return self.gateway.event_impact(
                document_id=event.document_id,
                security_id=event.security_id,
                segment_locator=event.evidence_locator,
                segment_text=event.fact,
                disclosure_time=event.disclosure_time.isoformat(),
                thesis_id=hypothesis.thesis_id,
                hypothesis_id=hypothesis.hypothesis_id,
                thesis_context=(hypothesis.thesis_core_view or hypothesis.statement),
                hypothesis_context=self._hypothesis_context(hypothesis, retrieval),
                event_type=event.event_type,
                occurred_on=(event.occurred_on.isoformat() if event.occurred_on else None),
                context=self._context(hypothesis, retrieval.items),
                repair_errors=repair_errors,
            )

        outcome = request_impact()
        impact = AgentImpact(hypothesis, retrieval, outcome)
        validation = EvidenceAgent.validate_impact(impact)
        if outcome.usable and not validation.valid:
            outcome = request_impact(_citation_repair_errors(validation))
            impact = AgentImpact(hypothesis, retrieval, outcome)
        return AgentRunResult(event_id=event.event_id, impacts=[impact])


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
