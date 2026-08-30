from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.ranking.profiles import profile_names


class RankedSearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    security_ids: list[str] = Field(min_length=1, max_length=20)
    industries: list[str] = Field(default_factory=list, max_length=20)
    direction: str = "看多"
    horizon: str = "12M"
    as_of: datetime | None = None
    object_types: list[str] = Field(default_factory=lambda: ["document_segment"])
    ranking_profile: str = "document_search"
    top_k: int = Field(default=10, ge=1, le=100)


class RankedItemOut(BaseModel):
    object_id: str
    object_type: str
    document_id: str
    locator: str
    content: str
    visibility_label: str
    rank: int
    keyword_score: float
    vector_score: float
    graph_score: float | None
    retrieval_score: float
    prior_score: float
    final_score: float
    feature_scores: dict[str, float]
    reason_codes: list[str]
    metadata: dict[str, object]


class RankedSearchOut(BaseModel):
    retrieval_version: str = "prior-rag-v1"
    embedding_version: str
    prior_snapshot_id: str | None
    ranking_profile: str
    items: list[RankedItemOut]


class TopicContextIn(BaseModel):
    security_id: str = Field(min_length=1, max_length=64)
    direction: str = "看多"
    horizon: str = "12M"
    as_of: datetime | None = None
    top_k: int = Field(default=3, ge=1, le=10)


class TopicRelationOut(BaseModel):
    object_id: str
    relation: str
    confidence: float
    reason: str | None = None
    citation_locators: list[str] = Field(default_factory=list)


class RankedTopicOut(BaseModel):
    topic_id: str
    name: str
    normalized_statement: str
    direction: str
    horizon: str
    rank: int
    score: float
    base_score: float
    feature_scores: dict[str, float]
    reason_codes: list[str]
    primary_eligible: bool
    citation_locators: list[str]
    relations: dict[str, list[TopicRelationOut]]
    metadata: dict[str, object]


class TopicContextOut(BaseModel):
    retrieval_version: str = "logic-topic-prior-v1"
    prior_snapshot_id: str | None
    primary_topic: RankedTopicOut | None
    alternative_topics: list[RankedTopicOut]


RANKING_PROFILES = profile_names()
