from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class RankingQuery:
    text: str
    security_ids: tuple[str, ...] = ()
    industries: tuple[str, ...] = ()
    direction: str = "看多"
    horizon: str = "12M"
    as_of: datetime | None = None
    profile: str = "document_search"
    top_k: int = 10


@dataclass(frozen=True)
class RankedCandidate:
    object_id: str
    object_type: str
    document_id: str
    locator: str
    content: str
    visibility_label: str
    keyword_score: float
    vector_score: float
    graph_score: float | None
    retrieval_score: float
    prior_score: float
    final_score: float
    rank: int
    feature_scores: dict[str, float] = field(default_factory=dict)
    reason_codes: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
