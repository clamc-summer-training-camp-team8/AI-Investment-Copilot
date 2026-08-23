"""Agent 能力模块共享的输入、输出和值对象。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.ai.contracts.validator import ValidationOutcome
from app.ai.retrieval import RetrievalResult


@dataclass(frozen=True)
class AgentEventInput:
    event_id: str
    document_id: str
    security_id: str
    evidence_locator: str
    fact: str
    disclosure_time: datetime
    event_type: str
    occurred_on: date | None = None


@dataclass(frozen=True)
class MetricRuleInput:
    metric_id: str
    expected_direction: str
    expected_value: Decimal | None = None
    invalidation_threshold: Decimal | None = None


@dataclass(frozen=True)
class HypothesisInput:
    thesis_id: str
    hypothesis_id: str
    statement: str
    thesis_core_view: str | None = None
    hypothesis_type: str | None = None
    importance: str | None = None
    expected_direction: str | None = None
    invalidation_rule: str | None = None
    metric_rules: tuple[MetricRuleInput, ...] = ()


@dataclass(frozen=True)
class AgentImpact:
    candidate: HypothesisInput
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
    citation_score: float = 0.0
    source_authority_score: float = 0.0
    freshness_score: float = 0.0
    claim_support_score: float = 0.0
    corroboration_score: float = 0.0
    transmission_score: float = 0.0


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
