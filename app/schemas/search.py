"""全局搜索 API 契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SearchType = Literal["security", "industry", "thesis", "event", "document"]
SearchTargetKind = Literal["security", "industry", "thesis", "event", "document_segment"]


class SearchTargetOut(BaseModel):
    kind: SearchTargetKind
    id: str


class GlobalSearchItemOut(BaseModel):
    id: str
    title: str
    subtitle: str = ""
    excerpt: str | None = None
    match_kind: str
    target: SearchTargetOut
    content_status: str | None = None
    content_kind: str | None = None
    retrieval_mode: str | None = None
    published_at: datetime | None = None


class GlobalSearchGroupOut(BaseModel):
    type: SearchType
    items: list[GlobalSearchItemOut] = Field(default_factory=list)


class GlobalSearchOut(BaseModel):
    query: str
    groups: list[GlobalSearchGroupOut]
    request_id: str
