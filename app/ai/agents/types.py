"""Agent 能力模块共享的输入、输出和值对象。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.ai.contracts.validator import ValidationOutcome
from app.ai.retrieval import RetrievalResult


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


@dataclass(frozen=True)
class EvidenceValidation:
    valid: bool
    cited_locators: tuple[str, ...]
    missing_locators: tuple[str, ...]
    unsupported_claims: tuple[str, ...]
    requires_human_review: bool


@dataclass(frozen=True)
class EvidenceGrade:
    score: float
    passed: bool
    cited_count: int
    valid_cited_count: int
    source_count: int
    stale_count: int
    missing: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceConsistency:
    entity_matched: bool
    fact_supported: bool
    conflicting: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class MetricExplainRunResult:
    security_id: str
    hypothesis_id: str
    outcome: ValidationOutcome


@dataclass(frozen=True)
class ReviewDraftRunResult:
    security_id: str
    thesis_id: str
    outcome: ValidationOutcome
