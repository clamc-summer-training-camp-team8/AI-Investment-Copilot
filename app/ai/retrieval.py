"""可替换的 RAG 检索接口与确定性关键词基线。

第一版不绑定向量数据库，先把权限、证券、时间窗口和引用定位这些业务约束固定下来。
后续可用 Chroma/pgvector 替换 `KeywordRetriever`，不改变 Agent 契约。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

RETRIEVAL_VERSION = "keyword-v1"
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


@dataclass(frozen=True)
class RetrievalDocument:
    document_id: str
    security_id: str
    locator: str
    content: str
    published_at: datetime
    visibility_label: str = "公开"
    source: str = "unknown"


@dataclass(frozen=True)
class RetrievalQuery:
    text: str
    security_id: str | None = None
    as_of: datetime | None = None
    allowed_visibility: frozenset[str] = frozenset({"公开"})
    top_k: int = 5


@dataclass(frozen=True)
class RetrievedChunk:
    document_id: str
    security_id: str
    locator: str
    content: str
    published_at: datetime
    visibility_label: str
    source: str
    score: float


@dataclass(frozen=True)
class RetrievalResult:
    query: RetrievalQuery
    items: list[RetrievedChunk]
    retrieval_version: str = RETRIEVAL_VERSION


class Retriever(Protocol):
    def add(self, documents: list[RetrievalDocument]) -> None: ...

    def search(self, query: RetrievalQuery) -> RetrievalResult: ...


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(text) if token.strip()}


class KeywordRetriever:
    """基于 token 重合度的可复现检索基线。"""

    def __init__(self) -> None:
        self._documents: dict[str, RetrievalDocument] = {}

    def add(self, documents: list[RetrievalDocument]) -> None:
        for document in documents:
            self._documents[document.locator] = document

    def search(self, query: RetrievalQuery) -> RetrievalResult:
        if query.top_k <= 0:
            return RetrievalResult(query=query, items=[])
        query_tokens = _tokens(query.text)
        candidates: list[RetrievedChunk] = []
        for document in self._documents.values():
            if query.security_id and document.security_id != query.security_id:
                continue
            if document.visibility_label not in query.allowed_visibility:
                continue
            if query.as_of and document.published_at > query.as_of:
                continue
            document_tokens = _tokens(document.content)
            overlap = query_tokens & document_tokens
            if not overlap:
                continue
            score = len(overlap) / max(len(query_tokens), 1)
            candidates.append(
                RetrievedChunk(
                    document_id=document.document_id,
                    security_id=document.security_id,
                    locator=document.locator,
                    content=document.content,
                    published_at=document.published_at,
                    visibility_label=document.visibility_label,
                    source=document.source,
                    score=round(score, 6),
                )
            )
        candidates.sort(key=lambda item: (-item.score, -item.published_at.timestamp(), item.locator))
        return RetrievalResult(query=query, items=candidates[: query.top_k])
