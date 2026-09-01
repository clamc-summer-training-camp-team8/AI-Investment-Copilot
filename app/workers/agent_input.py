"""Backend domain records 到 Event Impact Agent 输入的集中适配。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.ai.agents import AgentEventInput, HypothesisInput, MetricRuleInput
from app.ai.retrieval import RetrievalDocument
from app.core.domain import (
    AssetSearchHitRecord,
    DocumentSegmentRecord,
    HypothesisRecord,
    MetricMappingRecord,
    ThesisRecord,
)
from app.ingest.events import ExtractedEvent


class EventEvidenceUnavailable(ValueError):
    """Event 的主引用无法回查到真实 DocumentSegment。"""


@dataclass(frozen=True)
class EventAgentInputs:
    event: AgentEventInput
    current_event_evidence: RetrievalDocument


def index_current_event_segments(
    segments: list[DocumentSegmentRecord],
) -> dict[str, DocumentSegmentRecord]:
    """按 locator 建立当前事件原文索引，不做摘要回退。"""
    return {segment.locator: segment for segment in segments}


def build_event_agent_inputs(
    *,
    event: ExtractedEvent,
    security_id: str,
    segments_by_locator: Mapping[str, DocumentSegmentRecord],
    locator_override: str | None = None,
    visibility_label: str,
    source: str,
) -> EventAgentInputs:
    """同时构造结构化事实输入和 locator 对应的原文证据上下文。"""
    locator = locator_override or event.evidence_locator
    if locator is None:
        raise EventEvidenceUnavailable("缺少引用定位，无法进入证据链")
    segment = segments_by_locator.get(locator)
    if segment is None or segment.document_id != event.document_id or not segment.content.strip():
        raise EventEvidenceUnavailable("引用定位无法回查原文，转人工判断")

    event_input = AgentEventInput(
        event_id=event.event_id,
        document_id=event.document_id,
        security_id=security_id,
        evidence_locator=locator,
        fact=event.summary,
        disclosure_time=event.disclosure_time,
        event_type=event.event_type,
        occurred_on=event.occurred_on,
    )
    return EventAgentInputs(
        event=event_input,
        current_event_evidence=RetrievalDocument(
            document_id=segment.document_id,
            security_id=security_id,
            locator=segment.locator,
            content=segment.content,
            published_at=event.disclosure_time,
            visibility_label=visibility_label,
            source=source,
        ),
    )


def build_historical_rag_context(
    *,
    security_id: str,
    hits: list[AssetSearchHitRecord],
) -> list[RetrievalDocument]:
    """把 DB Hybrid RAG hit 的真实 metadata 显式传入 Agent Retriever。"""
    return [
        RetrievalDocument(
            document_id=hit.document_id,
            security_id=security_id,
            locator=hit.locator,
            content=hit.content,
            published_at=hit.published_at,
            visibility_label=hit.visibility_label,
            source=hit.source,
        )
        for hit in hits
        if hit.published_at is not None
    ]


def build_hypothesis_input(
    *,
    thesis_record: ThesisRecord,
    hypothesis: HypothesisRecord,
    mappings: list[MetricMappingRecord],
) -> HypothesisInput:
    """把 Thesis/Hypothesis/Metric Mapping 收敛为 typed Agent input。"""
    return HypothesisInput(
        thesis_id=thesis_record.thesis_id,
        hypothesis_id=hypothesis.hypothesis_id,
        statement=hypothesis.statement,
        thesis_core_view=thesis_record.core_view or None,
        hypothesis_type=hypothesis.hypothesis_type,
        importance=hypothesis.importance.value,
        expected_direction=(
            hypothesis.expected_direction.value
            if hypothesis.expected_direction is not None
            else None
        ),
        invalidation_rule=hypothesis.invalidation_rule,
        metric_rules=tuple(
            MetricRuleInput(
                metric_id=mapping.metric_id,
                expected_direction=mapping.expected_direction.value,
                expected_value=mapping.expected_value,
                expected_lower=mapping.expected_lower,
                expected_upper=mapping.expected_upper,
                invalidation_threshold=mapping.invalidation_threshold,
            )
            for mapping in mappings
        ),
    )
