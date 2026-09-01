"""知识库 AI 问答 API 契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AssistantContextIn(BaseModel):
    thesis_id: str | None = Field(default=None, min_length=1, max_length=64)
    security_id: str | None = Field(default=None, min_length=1, max_length=64)
    as_of: datetime | None = None


class AssistantHistoryItemIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class KnowledgeAnswerIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=2, max_length=1000)
    context: AssistantContextIn = Field(default_factory=AssistantContextIn)
    history: list[AssistantHistoryItemIn] = Field(default_factory=list, max_length=6)


class AnswerCitationOut(BaseModel):
    ref: str
    locator: str
    document_id: str
    title: str
    excerpt: str
    published_at: datetime | None = None
    content_status: str
    content_kind: str
    retrieval_mode: str


class KnowledgeAnswerOut(BaseModel):
    answer_id: str
    answer_status: Literal["supported", "partial", "insufficient_evidence"]
    ai_status: str
    answer: str
    inferences: list[str] = Field(default_factory=list)
    citations: list[AnswerCitationOut] = Field(default_factory=list)
    model_version: str
    prompt_version: str
    retrieval_version: str
    graph_snapshot_id: str | None = None
    generated_at: datetime
    request_id: str


class AnswerFeedbackIn(BaseModel):
    value: Literal["helpful", "not_helpful"]
    reason: (
        Literal["accurate", "useful_sources", "missing_sources", "incorrect", "irrelevant", "other"]
        | None
    ) = None
