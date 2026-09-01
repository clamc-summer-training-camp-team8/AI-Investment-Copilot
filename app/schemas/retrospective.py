"""Request and response contracts for the retrospective center."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

RetrospectiveTypeValue = Literal["周期", "结项", "专题", "人工"]
RetrospectiveStateValue = Literal["草稿", "待评审", "已发布", "已归档"]


class SourcePreviewIn(BaseModel):
    thesis_id: str = Field(min_length=1, max_length=64)
    period_start: date
    period_end: date
    data_cutoff_at: datetime


class RetrospectiveCreateIn(SourcePreviewIn):
    retrospective_type: RetrospectiveTypeValue
    title: str = Field(min_length=2, max_length=200)
    reviewer: str | None = Field(default=None, max_length=64)


class RetrospectiveDraftIn(BaseModel):
    content: dict[str, Any]
    lock_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=2, max_length=200)


class LockActionIn(BaseModel):
    lock_version: int = Field(ge=1)


class SubmitIn(LockActionIn):
    reviewer: str = Field(min_length=1, max_length=64)


class ReasonActionIn(LockActionIn):
    reason: str = Field(min_length=2, max_length=2000)


class PublishIn(LockActionIn):
    publish_reason: str = Field(min_length=2, max_length=2000)


class AiDraftIn(LockActionIn):
    pass


class RetrospectiveSourceOut(BaseModel):
    source_id: str
    source_type: str
    object_id: str
    object_version: str | None
    locator: str | None
    content_hash: str | None
    summary: str
    direction: str | None
    strength: str | None
    hypothesis_id: str | None
    disclosed_at: datetime | None
    confirmed_at: datetime | None
    visibility_label: str
    metadata: dict[str, Any]


class PreviewHypothesisOut(BaseModel):
    hypothesis_id: str
    name: str | None
    statement: str
    status: str


class SourcePreviewOut(BaseModel):
    thesis_id: str
    thesis_title: str
    security_id: str
    owner: str
    source_fingerprint: str
    source_count: int
    completeness_completed: int
    completeness_applicable: int
    completeness_score: Decimal
    missing_items: list[str]
    excluded_counts: dict[str, int]
    hypotheses: list[PreviewHypothesisOut]
    sources: list[RetrospectiveSourceOut]


class RetrospectiveOut(BaseModel):
    retrospective_id: str
    thesis_id: str
    thesis_title: str
    security_id: str
    retrospective_type: str
    title: str
    period_start: date
    period_end: date
    data_cutoff_at: datetime
    owner: str
    reviewer: str | None
    state: str
    visibility: str
    team: str | None
    source_fingerprint: str
    source_count: int
    completeness_completed: int
    completeness_applicable: int
    completeness_score: Decimal
    current_version: int
    lock_version: int
    ai_status: str
    hypothesis_result_counts: dict[str, int]
    strong_conflicts_handled: int
    strong_conflicts_total: int
    created_at: datetime | None
    updated_at: datetime | None
    submitted_at: datetime | None
    published_at: datetime | None
    archived_at: datetime | None


class RetrospectivePageOut(BaseModel):
    items: list[RetrospectiveOut]
    total: int
    limit: int
    offset: int


class RetrospectiveVersionOut(BaseModel):
    retrospective_id: str
    version: int
    content: dict[str, Any]
    source_fingerprint: str
    published_by: str
    publish_reason: str
    ai_run_id: str | None
    model_version: str | None
    prompt_version: str | None
    schema_version: str | None
    created_at: datetime | None


class RetrospectiveDetailOut(BaseModel):
    retrospective: RetrospectiveOut
    content: dict[str, Any]
    ai_candidate: dict[str, Any] | None
    sources: list[RetrospectiveSourceOut]
    versions: list[RetrospectiveVersionOut]
    allowed_actions: list[str]


class RetrospectiveOverviewOut(BaseModel):
    as_of: datetime | None
    total: int
    state_counts: dict[str, int]
    logic_changes: int
    validated_hypotheses: int
    pending_hypotheses: int
    strong_conflicts_handled: int
    strong_conflicts_total: int
    average_completeness: Decimal
    pending_reports: int
    is_truncated: bool
    definitions: dict[str, str]


class TimelineItemOut(BaseModel):
    source_id: str
    source_type: str
    title: str
    summary: str
    occurred_at: datetime | None
    disclosed_at: datetime | None
    confirmed_at: datetime | None
    direction: str | None
    strength: str | None
    hypothesis_id: str | None
    locator: str | None
    object_id: str
    object_version: str | None
    metadata: dict[str, Any]


class AiDraftOut(BaseModel):
    run_id: str
    status: Literal["completed", "failed"]
    requires_human_review: bool = True
    candidate: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)
    lock_version: int
