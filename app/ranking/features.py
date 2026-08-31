from __future__ import annotations

from dataclasses import dataclass


def _score(value: float) -> float:
    if not 0 <= value <= 1:
        raise ValueError("排序特征必须位于 [0, 1]")
    return float(value)


@dataclass(frozen=True)
class PriorFeatures:
    business_materiality: float = 0.5
    evidence_strength: float = 0.5
    persistence: float = 0.5
    verifiability: float = 0.5
    company_specificity: float = 0.5
    causal_strength: float = 0.5
    recency: float = 0.5
    conflict_attention: float = 0.0
    unresolved_conflict_severity: float = 0.0
    source_authority: float = 0.5
    direct_relevance: float = 0.5
    completeness: float = 0.5
    temporal_validity: float = 1.0
    novelty: float = 0.5
    traceability: float = 1.0
    statement_clarity: float = 0.5
    low_value_penalty: float = 0.0

    def __post_init__(self) -> None:
        for value in self.as_dict().values():
            _score(value)

    def as_dict(self) -> dict[str, float]:
        return {name: float(value) for name, value in self.__dict__.items()}


def topic_prior(features: PriorFeatures) -> float:
    score = (
        0.25 * features.business_materiality
        + 0.15 * features.evidence_strength
        + 0.15 * features.persistence
        + 0.15 * features.verifiability
        + 0.10 * features.company_specificity
        + 0.10 * features.causal_strength
        + 0.05 * features.recency
        + 0.05 * features.conflict_attention
    )
    return round(
        max(
            0.0,
            score
            - 0.20 * features.unresolved_conflict_severity
            - 0.25 * features.low_value_penalty,
        ),
        8,
    )


def evidence_prior(features: PriorFeatures) -> float:
    score = (
        0.25 * features.source_authority
        + 0.20 * features.direct_relevance
        + 0.15 * features.completeness
        + 0.15 * features.temporal_validity
        + 0.10 * features.novelty
        + 0.10 * features.traceability
        + 0.05 * features.statement_clarity
    )
    return round(max(0.0, score - 0.35 * features.low_value_penalty), 8)


def score_for_object(object_type: str, features: PriorFeatures) -> float:
    if object_type == "logic_topic":
        return topic_prior(features)
    if object_type in {"hypothesis", "evidence", "document_segment"}:
        return evidence_prior(features)
    raise ValueError(f"不支持的排序对象类型: {object_type}")
