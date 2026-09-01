"""新事件对一组既有投资假设的批量影响分析能力。"""

from __future__ import annotations

from typing import Any

from app.ai.agents.evidence import EvidenceAgent
from app.ai.agents.types import (
    AgentEventInput,
    AgentImpact,
    AgentRunResult,
    EvidenceValidation,
    HypothesisInput,
)
from app.ai.contracts.validator import ValidationOutcome
from app.ai.gateway import Gateway
from app.ai.retrieval import RetrievalQuery, RetrievalResult, RetrievedChunk, Retriever
from app.core.enums import AiStatus


class InvestmentLogicChangeAgent:
    """一次分析一个新事件对一组候选投资假设的影响。"""

    def __init__(self, *, gateway: Gateway, retriever: Retriever) -> None:
        self.gateway = gateway
        self.retriever = retriever

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
            "thesis_core_view": hypothesis.thesis_core_view,
            "hypothesis_type": hypothesis.hypothesis_type,
            "importance": hypothesis.importance,
            "expected_direction": hypothesis.expected_direction,
            "invalidation_rule": hypothesis.invalidation_rule,
            "metric_rules": [
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

    @staticmethod
    def _evidence_context(
        event: AgentEventInput,
        hypothesis: HypothesisInput,
        chunks: list[RetrievedChunk],
    ) -> dict[str, object]:
        return {
            "thesis_id": hypothesis.thesis_id,
            "hypothesis_id": hypothesis.hypothesis_id,
            "evidence": [
                {
                    "context_type": (
                        "current_event_evidence"
                        if chunk.locator == event.evidence_locator
                        else "historical_rag"
                    ),
                    "document_id": chunk.document_id,
                    "locator": chunk.locator,
                    "content": chunk.content,
                    "published_at": chunk.published_at.isoformat(),
                    "source": chunk.source,
                    "retrieval_score": chunk.score,
                    "score_components": chunk.metadata.get("score_components", {}),
                    "graph_paths": chunk.metadata.get("graph_paths", []),
                    "graph_snapshot": chunk.metadata.get("graph_snapshot"),
                }
                for chunk in chunks
            ],
        }

    def analyze(
        self,
        event: AgentEventInput,
        hypotheses: tuple[HypothesisInput, ...],
        *,
        allowed_visibility: frozenset[str] = frozenset({"公开"}),
        top_k: int = 3,
    ) -> AgentRunResult:
        if not hypotheses:
            return AgentRunResult(event_id=event.event_id, impacts=[])

        retrievals = [
            self.retriever.search(
                RetrievalQuery(
                    text=f"{event.fact} {hypothesis.statement}",
                    security_id=event.security_id,
                    as_of=event.disclosure_time,
                    allowed_visibility=allowed_visibility,
                    top_k=top_k,
                    seed_node_ids=frozenset({f"hypothesis:{hypothesis.hypothesis_id}"}),
                )
            )
            for hypothesis in hypotheses
        ]
        candidates = [
            self._hypothesis_context(hypothesis, retrieval)
            for hypothesis, retrieval in zip(hypotheses, retrievals, strict=True)
        ]
        evidence_contexts = [
            self._evidence_context(event, hypothesis, retrieval.items)
            for hypothesis, retrieval in zip(hypotheses, retrievals, strict=True)
        ]

        def request_impact(repair_errors: list[str] | None = None) -> ValidationOutcome:
            return self.gateway.event_impact(
                document_id=event.document_id,
                security_id=event.security_id,
                segment_locator=event.evidence_locator,
                segment_text=event.fact,
                disclosure_time=event.disclosure_time.isoformat(),
                candidates=candidates,
                evidence_contexts=evidence_contexts,
                event_type=event.event_type,
                occurred_on=(event.occurred_on.isoformat() if event.occurred_on else None),
                repair_errors=repair_errors,
            )

        outcome = request_impact()
        repair_errors = _batch_contract_errors(outcome, hypotheses)
        if outcome.usable and not repair_errors:
            impacts = _split_batch_outcome(event, hypotheses, retrievals, outcome)
            for impact in impacts:
                validation = EvidenceAgent.validate_impact(impact)
                if not validation.valid:
                    repair_errors.extend(
                        f"{impact.candidate.hypothesis_id}: {error}"
                        for error in _citation_repair_errors(validation)
                    )
        if outcome.usable and repair_errors:
            outcome = request_impact(repair_errors)

        threshold = getattr(
            getattr(getattr(self.gateway, "settings", None), "rules", None),
            "low_confidence_cutoff",
            0.6,
        )
        impacts = _split_batch_outcome(
            event,
            hypotheses,
            retrievals,
            outcome,
            low_confidence_cutoff=float(threshold),
        )
        return AgentRunResult(event_id=event.event_id, impacts=impacts)

    def analyze_many(
        self,
        events: tuple[AgentEventInput, ...],
        hypotheses: tuple[HypothesisInput, ...],
        *,
        allowed_visibility: frozenset[str] = frozenset({"公开"}),
        top_k: int = 3,
    ) -> list[AgentRunResult]:
        """一次模型请求分析一批事件与同一组候选假设。"""
        if not events:
            return []
        if not hypotheses:
            return [AgentRunResult(event_id=event.event_id, impacts=[]) for event in events]

        retrieval_sets, request_events = self._prepare_many(
            events,
            hypotheses,
            allowed_visibility=allowed_visibility,
            top_k=top_k,
        )

        outcomes = self.gateway.event_impacts(
            document_id=events[0].document_id,
            security_id=events[0].security_id,
            events=request_events,
        )
        threshold = getattr(
            getattr(getattr(self.gateway, "settings", None), "rules", None),
            "low_confidence_cutoff",
            0.6,
        )
        return [
            AgentRunResult(
                event_id=event.event_id,
                impacts=_split_batch_outcome(
                    event,
                    hypotheses,
                    retrievals,
                    outcome,
                    low_confidence_cutoff=float(threshold),
                ),
            )
            for event, retrievals, outcome in zip(events, retrieval_sets, outcomes, strict=True)
        ]

    async def analyze_many_async(
        self,
        events: tuple[AgentEventInput, ...],
        hypotheses: tuple[HypothesisInput, ...],
        *,
        allowed_visibility: frozenset[str] = frozenset({"公开"}),
        top_k: int = 3,
    ) -> list[AgentRunResult]:
        if not events:
            return []
        if not hypotheses:
            return [AgentRunResult(event_id=event.event_id, impacts=[]) for event in events]
        # 每个事件仍一次判断全部候选假设；但不再把同一份长资料的多个
        # 事件塞进一个响应。完整的嵌套 JSON 会随「事件数 × 假设数」急剧膨胀，
        # 真实模型容易在输出上限处截断，从而把本可用的资料全部转人工。
        # 单事件批次既保留假设间的相对判断，也将失败严格隔离到该事件。
        if len(events) > 1:
            results: list[AgentRunResult] = []
            for event in events:
                results.extend(
                    await self.analyze_many_async(
                        (event,),
                        hypotheses,
                        allowed_visibility=allowed_visibility,
                        top_k=top_k,
                    )
                )
            return results

        retrieval_sets, request_events = self._prepare_many(
            events,
            hypotheses,
            allowed_visibility=allowed_visibility,
            top_k=top_k,
        )
        outcomes = await self.gateway.event_impacts_async(
            document_id=events[0].document_id,
            security_id=events[0].security_id,
            events=request_events,
        )
        threshold = getattr(
            getattr(getattr(self.gateway, "settings", None), "rules", None),
            "low_confidence_cutoff",
            0.6,
        )
        return [
            AgentRunResult(
                event_id=event.event_id,
                impacts=_split_batch_outcome(
                    event,
                    hypotheses,
                    retrievals,
                    outcome,
                    low_confidence_cutoff=float(threshold),
                ),
            )
            for event, retrievals, outcome in zip(events, retrieval_sets, outcomes, strict=True)
        ]

    def _prepare_many(
        self,
        events: tuple[AgentEventInput, ...],
        hypotheses: tuple[HypothesisInput, ...],
        *,
        allowed_visibility: frozenset[str],
        top_k: int,
    ) -> tuple[list[list[RetrievalResult]], list[dict[str, Any]]]:
        retrieval_sets: list[list[RetrievalResult]] = []
        request_events: list[dict[str, Any]] = []
        for event in events:
            retrievals = [
                self.retriever.search(
                    RetrievalQuery(
                        text=f"{event.fact} {hypothesis.statement}",
                        security_id=event.security_id,
                        as_of=event.disclosure_time,
                        allowed_visibility=allowed_visibility,
                        top_k=top_k,
                        seed_node_ids=frozenset({f"hypothesis:{hypothesis.hypothesis_id}"}),
                    )
                )
                for hypothesis in hypotheses
            ]
            retrieval_sets.append(retrievals)
            request_events.append(
                {
                    "event_id": event.event_id,
                    "segment_locator": event.evidence_locator,
                    "segment_text": event.fact,
                    "disclosure_time": event.disclosure_time.isoformat(),
                    "event_type": event.event_type,
                    "occurred_on": event.occurred_on.isoformat() if event.occurred_on else None,
                    "candidates": [
                        self._hypothesis_context(hypothesis, retrieval)
                        for hypothesis, retrieval in zip(hypotheses, retrievals, strict=True)
                    ],
                    "evidence_contexts": [
                        self._evidence_context(event, hypothesis, retrieval.items)
                        for hypothesis, retrieval in zip(hypotheses, retrievals, strict=True)
                    ],
                }
            )
        return retrieval_sets, request_events


def _batch_contract_errors(
    outcome: ValidationOutcome,
    hypotheses: tuple[HypothesisInput, ...],
) -> list[str]:
    if not outcome.usable:
        return []
    raw_impacts = outcome.payload.get("impacts")
    if not isinstance(raw_impacts, list):
        return ["impacts 必须为数组"]
    expected = [(item.thesis_id, item.hypothesis_id) for item in hypotheses]
    actual = [
        (str(item.get("thesis_id") or ""), str(item.get("hypothesis_id") or ""))
        for item in raw_impacts
        if isinstance(item, dict)
    ]
    errors: list[str] = []
    if len(raw_impacts) != len(expected):
        errors.append(f"输入 {len(expected)} 条候选假设，必须返回 {len(expected)} 条 Impact")
    if len(actual) != len(raw_impacts):
        errors.append("impacts 中存在非对象元素")
    if actual != expected:
        errors.append("impacts 必须按输入顺序返回，并保持 thesis_id/hypothesis_id 完全一致")
    return errors


def _split_batch_outcome(
    event: AgentEventInput,
    hypotheses: tuple[HypothesisInput, ...],
    retrievals: list[RetrievalResult],
    outcome: ValidationOutcome,
    *,
    low_confidence_cutoff: float = 0.6,
) -> list[AgentImpact]:
    contract_errors = _batch_contract_errors(outcome, hypotheses)
    raw_impacts = outcome.payload.get("impacts")
    impact_payloads = raw_impacts if isinstance(raw_impacts, list) else []
    results: list[AgentImpact] = []
    for index, (hypothesis, retrieval) in enumerate(zip(hypotheses, retrievals, strict=True)):
        raw = impact_payloads[index] if index < len(impact_payloads) else None
        valid_identity = (
            isinstance(raw, dict)
            and raw.get("thesis_id") == hypothesis.thesis_id
            and raw.get("hypothesis_id") == hypothesis.hypothesis_id
        )
        if not outcome.usable or contract_errors or not valid_identity:
            child = ValidationOutcome(
                ai_status=AiStatus.PARSE_FAILED,
                payload=_failed_impact_payload(event, hypothesis, outcome.payload),
                errors=[*outcome.errors, *contract_errors],
                repaired=outcome.repaired,
            )
        else:
            assert isinstance(raw, dict)
            payload = _child_payload(event, raw, outcome.payload)
            confidence = _signal_confidence(raw)
            status = (
                AiStatus.LOW_CONFIDENCE
                if confidence is not None and confidence < low_confidence_cutoff
                else AiStatus.CANDIDATE
            )
            payload["ai_status"] = status.value
            child = ValidationOutcome(
                ai_status=status,
                payload=payload,
                errors=(
                    [f"置信度 {confidence} 低于阈值 {low_confidence_cutoff}"]
                    if status is AiStatus.LOW_CONFIDENCE
                    else []
                ),
                repaired=outcome.repaired,
            )
        results.append(AgentImpact(hypothesis, retrieval, child))
    return results


def _child_payload(
    event: AgentEventInput,
    impact: dict[str, Any],
    aggregate: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "document_id": aggregate.get("document_id", event.document_id),
        "security_id": aggregate.get("security_id", event.security_id),
        "thesis_id": impact.get("thesis_id"),
        "hypothesis_id": impact.get("hypothesis_id"),
        "relevance": impact.get("relevance"),
        "event": aggregate.get("event") or _event_payload(event),
        "inference": impact.get("inference"),
        "signal": impact.get("signal"),
        "citations": impact.get("citations", []),
        "unsupported_claims": impact.get("unsupported_claims", []),
        "model_version": aggregate.get("model_version"),
        "prompt_version": aggregate.get("prompt_version"),
        "generated_at": aggregate.get("generated_at"),
    }
    metadata = aggregate.get("model_metadata")
    if isinstance(metadata, dict):
        payload["model_metadata"] = metadata
    return payload


def _failed_impact_payload(
    event: AgentEventInput,
    hypothesis: HypothesisInput,
    aggregate: dict[str, Any],
) -> dict[str, Any]:
    return {
        "document_id": event.document_id,
        "security_id": event.security_id,
        "thesis_id": hypothesis.thesis_id,
        "hypothesis_id": hypothesis.hypothesis_id,
        "relevance": "待定",
        "event": aggregate.get("event") or _event_payload(event),
        "signal": {"requires_human_review": True},
        "citations": [],
        "unsupported_claims": [],
        "model_version": aggregate.get("model_version"),
        "prompt_version": aggregate.get("prompt_version"),
        "generated_at": aggregate.get("generated_at"),
        "ai_status": AiStatus.PARSE_FAILED.value,
    }


def _event_payload(event: AgentEventInput) -> dict[str, object]:
    return {
        "event_type": event.event_type,
        "event_time": event.occurred_on.isoformat() if event.occurred_on else None,
        "disclosure_time": event.disclosure_time.isoformat(),
        "fact": event.fact,
        "evidence_locator": event.evidence_locator,
    }


def _signal_confidence(impact: dict[str, Any]) -> float | None:
    signal = impact.get("signal")
    value = signal.get("confidence") if isinstance(signal, dict) else None
    return float(value) if isinstance(value, int | float) else None


def _citation_repair_errors(validation: EvidenceValidation) -> list[str]:
    """把证据校验失败转换为模型可执行、但不泄露额外数据的修复要求。"""
    errors: list[str] = []
    if validation.missing_locators:
        errors.append(f"引用不存在或不在允许范围内: {', '.join(validation.missing_locators)}")
    if validation.unsupported_claims:
        errors.append("删除或明确标注 unsupported_claims 中没有证据支持的陈述")
    return errors or ["补全有效引用，且不要新增输入之外的事实"]
