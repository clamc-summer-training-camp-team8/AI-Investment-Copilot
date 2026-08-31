"""固定真实案例 Demo 的 API 契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Base(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)


class DemoUploadOut(Base):
    document_id: str
    evidence_ids: list[str]
    relation_ids: list[str]
    result_source: Literal["preset_ai_result"]
    duplicate: bool
    next_url: str


class AffectedHypothesisOut(Base):
    hypothesis_id: str
    statement: str
    metric_name: str
    actual_value: str
    invalidation_threshold: str
    direction: str


class EvidenceAnalysisOut(Base):
    evidence_id: str
    relation_id: str
    document_id: str
    document_title: str
    disclosed_at: datetime
    fact_excerpt: str
    hypothesis_id: str
    hypothesis_statement: str
    affected_hypotheses: list[AffectedHypothesisOut]
    direction: str
    strength: str
    transmission_path: str
    ai_confidence: str
    ai_status: str
    model_version: str
    prompt_version: str
    evidence_locator: str
    result_source: Literal["preset_ai_result"]
    relation_status: str
    can_manage: bool
    review_reason: str | None = None


class CitationSegmentOut(Base):
    locator: str
    ordinal: int
    page: int | None = None
    content: str


class CitationContextOut(Base):
    document_id: str
    document_title: str
    document_type: str
    disclosed_at: datetime
    locator: str
    page: int | None = None
    previous: CitationSegmentOut | None = None
    target: CitationSegmentOut
    next: CitationSegmentOut | None = None
    source_url: str | None = None


class HealthMetricOut(Base):
    name: str
    value: str
    trend: str


class HypothesisHealthOut(Base):
    hypothesis_id: str
    statement: str
    importance: str
    support_confirmed: int
    conflict_confirmed: int
    pending: int
    health: str
    health_reason: str
    metric: HealthMetricOut
    invalidation: str


class TimelineEventOut(Base):
    event_id: str
    thesis_id: str
    dimension: Literal[
        "material",
        "ai_analysis",
        "human_review",
        "hypothesis_health",
        "logic_decision",
    ]
    event_type: str
    occurred_at: datetime
    actor_type: Literal["human", "system", "preset_ai"]
    actor_name: str
    summary: str
    related_object_type: str | None = None
    related_object_id: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    reason: str | None = None
    detail_url: str | None = None


class TimelinePageOut(Base):
    items: list[TimelineEventOut] = Field(default_factory=list)
    total: int
    limit: int
    offset: int
