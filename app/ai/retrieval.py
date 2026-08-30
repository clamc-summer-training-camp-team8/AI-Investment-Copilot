"""可替换的 RAG 检索接口与确定性关键词基线。

第一版不绑定向量数据库，先把权限、证券、时间窗口和引用定位这些业务约束固定下来。
后续可用 Chroma/pgvector 替换 `KeywordRetriever`，不改变 Agent 契约。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Protocol

from app.ai.embeddings import LOCAL_EMBEDDING_VERSION, embed_text

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
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalQuery:
    text: str
    security_id: str | None = None
    as_of: datetime | None = None
    allowed_visibility: frozenset[str] = frozenset({"公开"})
    top_k: int = 5
    # 上游已经形成候选池时，Graph 只能在该池内重排/补强。None 表示开放语料检索；
    # 空集合表示没有允许候选。该约束与证券、时间、可见性共同生效。
    allowed_document_ids: frozenset[str] | None = None
    # Graph RAG 可用稳定节点 ID 定向检索；普通 Retriever 会安全忽略该字段。
    seed_node_ids: frozenset[str] = frozenset()


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
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalResult:
    query: RetrievalQuery
    items: list[RetrievedChunk]
    retrieval_version: str = RETRIEVAL_VERSION


class Retriever(Protocol):
    def add(self, documents: list[RetrievalDocument]) -> None: ...

    def search(self, query: RetrievalQuery) -> RetrievalResult: ...


def document_allowed(document: RetrievalDocument, query: RetrievalQuery) -> bool:
    """统一执行候选池、证券、权限和时间边界。"""

    if (
        query.allowed_document_ids is not None
        and document.document_id not in query.allowed_document_ids
    ):
        return False
    if query.security_id and document.security_id != query.security_id:
        return False
    if document.visibility_label not in query.allowed_visibility:
        return False
    return not (query.as_of and document.published_at > query.as_of)


def tokenize(text: str) -> set[str]:
    """稳定的中英文检索 token；Graph RAG 与关键词基线共享同一口径。"""

    return {token.lower() for token in _TOKEN_RE.findall(text) if token.strip()}


def tokenize_zh_terms(text: str) -> list[str]:
    """面向中文公告的稳定检索词元。

    单字只用于兼容原关键词基线；BM25 使用连续中文片段的 2/3-gram 与 ASCII
    单词，避免“公司、公告、股份”一类高频单字支配相关度。实现不依赖在线分词
    服务，因此离线消融和生产回放可复现。
    """

    terms = re.findall(r"[a-z0-9]+", text.lower())
    for segment in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(segment) == 1:
            terms.append(segment)
            continue
        terms.extend(segment[index : index + 2] for index in range(len(segment) - 1))
        if len(segment) >= 3:
            terms.extend(segment[index : index + 3] for index in range(len(segment) - 2))
    return terms


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
        query_tokens = tokenize(query.text)
        candidates: list[RetrievedChunk] = []
        for document in self._documents.values():
            if not document_allowed(document, query):
                continue
            document_tokens = tokenize(document.content)
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
                    metadata=dict(document.metadata),
                )
            )
        candidates.sort(
            key=lambda item: (-item.score, -item.published_at.timestamp(), item.locator)
        )
        return RetrievalResult(query=query, items=candidates[: query.top_k])


class BM25Retriever:
    """中文 2/3-gram BM25 召回；参数在版本内冻结。"""

    retrieval_version = "bm25-zh-ngram-v1[k1=1.2,b=0.75]"

    def __init__(self, *, k1: float = 1.2, b: float = 0.75) -> None:
        if k1 <= 0 or not 0 <= b <= 1:
            raise ValueError("BM25 参数范围无效")
        self.k1 = k1
        self.b = b
        self._documents: dict[str, RetrievalDocument] = {}

    def add(self, documents: list[RetrievalDocument]) -> None:
        for document in documents:
            self._documents[document.locator] = document

    def search(self, query: RetrievalQuery) -> RetrievalResult:
        if query.top_k <= 0:
            return RetrievalResult(query=query, items=[], retrieval_version=self.retrieval_version)
        allowed = [
            document
            for document in self._documents.values()
            if document_allowed(document, query)
        ]
        if not allowed:
            return RetrievalResult(query=query, items=[], retrieval_version=self.retrieval_version)
        document_terms = {
            document.locator: tokenize_zh_terms(document.content) for document in allowed
        }
        average_length = sum(map(len, document_terms.values())) / len(document_terms)
        query_terms = set(tokenize_zh_terms(query.text))
        document_frequency = Counter(
            term for terms in document_terms.values() for term in set(terms) if term in query_terms
        )
        candidates: list[RetrievedChunk] = []
        for document in allowed:
            terms = document_terms[document.locator]
            frequencies = Counter(terms)
            score = 0.0
            for term in query_terms:
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                matched_documents = document_frequency[term]
                inverse_document_frequency = math.log(
                    1 + (len(allowed) - matched_documents + 0.5) / (matched_documents + 0.5)
                )
                length_norm = 1 - self.b + self.b * len(terms) / max(average_length, 1)
                score += inverse_document_frequency * (
                    frequency * (self.k1 + 1) / (frequency + self.k1 * length_norm)
                )
            if score <= 0:
                continue
            candidates.append(
                RetrievedChunk(
                    document_id=document.document_id,
                    security_id=document.security_id,
                    locator=document.locator,
                    content=document.content,
                    published_at=document.published_at,
                    visibility_label=document.visibility_label,
                    source=document.source,
                    score=round(score, 8),
                    metadata={**document.metadata, "bm25_score": round(score, 8)},
                )
            )
        candidates.sort(
            key=lambda item: (-item.score, -item.published_at.timestamp(), item.locator)
        )
        return RetrievalResult(
            query=query,
            items=candidates[: query.top_k],
            retrieval_version=self.retrieval_version,
        )


class ChineseVectorRetriever:
    """本地中文哈希向量召回。

    复用版本化 ``hash-char-2gram-v1`` embedding，用于可复现离线消融；它不是
    通用语义模型，线上可由同一 Retriever 契约替换为已授权中文 embedding。
    """

    retrieval_version = f"chinese-vector-v1[{LOCAL_EMBEDDING_VERSION}]"

    def __init__(self) -> None:
        self._documents: dict[str, RetrievalDocument] = {}
        self._vectors: dict[str, list[float]] = {}

    def add(self, documents: list[RetrievalDocument]) -> None:
        for document in documents:
            self._documents[document.locator] = document
            self._vectors[document.locator] = embed_text(document.content)

    def search(self, query: RetrievalQuery) -> RetrievalResult:
        if query.top_k <= 0:
            return RetrievalResult(query=query, items=[], retrieval_version=self.retrieval_version)
        query_vector = embed_text(query.text)
        candidates: list[RetrievedChunk] = []
        for document in self._documents.values():
            if not document_allowed(document, query):
                continue
            similarity = sum(
                left * right
                for left, right in zip(query_vector, self._vectors[document.locator], strict=True)
            )
            if similarity <= 0:
                continue
            candidates.append(
                RetrievedChunk(
                    document_id=document.document_id,
                    security_id=document.security_id,
                    locator=document.locator,
                    content=document.content,
                    published_at=document.published_at,
                    visibility_label=document.visibility_label,
                    source=document.source,
                    score=round(similarity, 8),
                    metadata={
                        **document.metadata,
                        "vector_similarity": round(similarity, 8),
                        "embedding_version": LOCAL_EMBEDDING_VERSION,
                    },
                )
            )
        candidates.sort(
            key=lambda item: (-item.score, -item.published_at.timestamp(), item.locator)
        )
        return RetrievalResult(
            query=query,
            items=candidates[: query.top_k],
            retrieval_version=self.retrieval_version,
        )


class CandidateUnionRetriever:
    """保持主排序不变，只用补充召回器填充主召回未命中的候选。"""

    retrieval_version = "controlled-candidate-union-v1"

    def __init__(
        self,
        *,
        primary: Retriever,
        supplemental: tuple[Retriever, ...],
        supplemental_score_scale: float = 0.5,
    ) -> None:
        if not 0 < supplemental_score_scale <= 1:
            raise ValueError("补充召回分数比例必须在 (0, 1]")
        self.primary = primary
        self.supplemental = supplemental
        self.supplemental_score_scale = supplemental_score_scale

    def add(self, documents: list[RetrievalDocument]) -> None:
        self.primary.add(documents)
        for retriever in self.supplemental:
            if retriever is not self.primary:
                retriever.add(documents)

    def search(self, query: RetrievalQuery) -> RetrievalResult:
        primary = self.primary.search(query)
        items = list(primary.items)
        seen = {item.locator for item in items}
        floor = min((item.score for item in items), default=1.0)
        versions = [primary.retrieval_version]
        extras: list[RetrievedChunk] = []
        for retriever in self.supplemental:
            result = retriever.search(query)
            versions.append(result.retrieval_version)
            maximum = max((item.score for item in result.items), default=1.0)
            for item in result.items:
                if item.locator in seen:
                    continue
                seen.add(item.locator)
                extras.append(
                    replace(
                        item,
                        score=round(
                            floor * self.supplemental_score_scale * item.score / maximum, 8
                        ),
                        metadata={
                            **item.metadata,
                            "candidate_union_source": result.retrieval_version,
                        },
                    )
                )
        extras.sort(key=lambda item: (-item.score, -item.published_at.timestamp(), item.locator))
        items.extend(extras)
        return RetrievalResult(
            query=query,
            items=items[: query.top_k],
            retrieval_version=f"{self.retrieval_version}[{'+'.join(versions)}]",
        )


GOVERNANCE_TERMS = frozenset(
    {
        "股东大会",
        "董事会",
        "监事会",
        "股份质押",
        "持股变动",
        "员工持股",
        "募集资金",
        "现金管理",
        "股份回购",
        "回购注销",
        "股权激励",
        "股票期权",
        "利润分配",
        "章程",
        "月报表",
        "认股权",
        "关连交易",
        "关联交易",
    }
)


class AnnouncementTypePriorRetriever:
    """查询感知的公告类型先验，不读取评测标签。"""

    retrieval_version = "announcement-prior-v1"

    def __init__(
        self,
        retriever: Retriever,
        *,
        governance_penalty: float = 0.25,
        matching_boost: float = 1.08,
        candidate_multiplier: int = 1,
    ) -> None:
        self.retriever = retriever
        self.governance_penalty = governance_penalty
        self.matching_boost = matching_boost
        self.candidate_multiplier = max(1, candidate_multiplier)

    def add(self, documents: list[RetrievalDocument]) -> None:
        self.retriever.add(documents)

    def search(self, query: RetrievalQuery) -> RetrievalResult:
        expanded = replace(query, top_k=query.top_k * self.candidate_multiplier)
        result = self.retriever.search(expanded)
        query_governance = _contains_any(query.text, GOVERNANCE_TERMS)
        ranked: list[RetrievedChunk] = []
        for item in result.items:
            title = item.source or ""
            document_governance = _contains_any(title, GOVERNANCE_TERMS)
            prior = 1.0
            reason = "neutral"
            if document_governance and not query_governance:
                prior = self.governance_penalty
                reason = "governance_hard_negative"
            elif document_governance and query_governance:
                prior = self.matching_boost
                reason = "governance_query_match"
            ranked.append(
                replace(
                    item,
                    score=round(item.score * prior, 8),
                    metadata={
                        **item.metadata,
                        "announcement_type_prior": prior,
                        "announcement_type_reason": reason,
                    },
                )
            )
        ranked.sort(key=lambda item: (-item.score, -item.published_at.timestamp(), item.locator))
        return RetrievalResult(
            query=query,
            items=ranked[: query.top_k],
            retrieval_version=f"{self.retrieval_version}[{result.retrieval_version}]",
        )


class DiversityReranker:
    """对近重复公告做 MMR 重排，保留相关度同时扩大 Top-K 覆盖。"""

    retrieval_version = "diversity-mmr-v1[lambda=0.82]"

    def __init__(
        self,
        retriever: Retriever,
        *,
        relevance_weight: float = 0.82,
        candidate_multiplier: int = 3,
    ) -> None:
        if not 0 <= relevance_weight <= 1:
            raise ValueError("MMR relevance_weight 必须在 [0, 1]")
        self.retriever = retriever
        self.relevance_weight = relevance_weight
        self.candidate_multiplier = max(1, candidate_multiplier)

    def add(self, documents: list[RetrievalDocument]) -> None:
        self.retriever.add(documents)

    def search(self, query: RetrievalQuery) -> RetrievalResult:
        expanded = replace(query, top_k=query.top_k * self.candidate_multiplier)
        result = self.retriever.search(expanded)
        remaining = list(result.items)
        if not remaining:
            return RetrievalResult(
                query=query,
                items=[],
                retrieval_version=f"{self.retrieval_version}[{result.retrieval_version}]",
            )
        maximum = max(item.score for item in remaining) or 1.0
        selected: list[RetrievedChunk] = []
        while remaining and len(selected) < query.top_k:
            best = max(
                remaining,
                key=lambda item: (
                    self.relevance_weight * (item.score / maximum)
                    - (1 - self.relevance_weight)
                    * max((_document_similarity(item, chosen) for chosen in selected), default=0.0),
                    item.score,
                    item.published_at.timestamp(),
                    item.locator,
                ),
            )
            similarity = max(
                (_document_similarity(best, chosen) for chosen in selected), default=0.0
            )
            selected.append(
                replace(
                    best,
                    metadata={
                        **best.metadata,
                        "diversity_max_similarity": round(similarity, 8),
                    },
                )
            )
            remaining.remove(best)
        return RetrievalResult(
            query=query,
            items=selected,
            retrieval_version=f"{self.retrieval_version}[{result.retrieval_version}]",
        )


def _contains_any(text: str, terms: frozenset[str]) -> bool:
    normalized = text.lower()
    return any(term.lower() in normalized for term in terms)


def _document_similarity(left: RetrievedChunk, right: RetrievedChunk) -> float:
    left_title = set(tokenize_zh_terms(left.source))
    right_title = set(tokenize_zh_terms(right.source))
    if not left_title or not right_title:
        return 0.0
    return len(left_title & right_title) / len(left_title | right_title)


class HybridRetriever:
    """合并全文和向量召回结果；具体向量库由注入的 Retriever 决定。"""

    def __init__(
        self,
        *,
        lexical: Retriever,
        vector: Retriever,
        lexical_weight: float = 0.5,
        vector_weight: float = 0.5,
        candidate_multiplier: int = 3,
        rrf_k: int = 60,
    ) -> None:
        if lexical_weight < 0 or vector_weight < 0 or lexical_weight + vector_weight == 0:
            raise ValueError("检索权重必须非负且至少一个大于零")
        self.lexical = lexical
        self.vector = vector
        total = lexical_weight + vector_weight
        self.lexical_weight = lexical_weight / total
        self.vector_weight = vector_weight / total
        self.candidate_multiplier = max(candidate_multiplier, 1)
        self.rrf_k = max(rrf_k, 1)

    def add(self, documents: list[RetrievalDocument]) -> None:
        self.lexical.add(documents)
        if self.vector is not self.lexical:
            self.vector.add(documents)

    def search(self, query: RetrievalQuery) -> RetrievalResult:
        if query.top_k <= 0:
            return RetrievalResult(query=query, items=[], retrieval_version="hybrid-v1")
        expanded = replace(query, top_k=query.top_k * self.candidate_multiplier)
        lexical_result = self.lexical.search(expanded)
        vector_result = self.vector.search(expanded)
        scores: dict[str, float] = {}
        chunks: dict[str, RetrievedChunk] = {}
        for result, weight in (
            (lexical_result, self.lexical_weight),
            (vector_result, self.vector_weight),
        ):
            for rank, item in enumerate(result.items, start=1):
                if query.security_id and item.security_id != query.security_id:
                    continue
                if item.visibility_label not in query.allowed_visibility:
                    continue
                if query.as_of and item.published_at > query.as_of:
                    continue
                chunks[item.locator] = item
                scores[item.locator] = scores.get(item.locator, 0.0) + weight / (self.rrf_k + rank)
        ranked = sorted(
            chunks.values(),
            key=lambda item: (-scores[item.locator], -item.published_at.timestamp(), item.locator),
        )
        items = [
            replace(item, score=round(scores[item.locator], 8)) for item in ranked[: query.top_k]
        ]
        version = f"hybrid-v1[{lexical_result.retrieval_version}+{vector_result.retrieval_version}]"
        return RetrievalResult(query=query, items=items, retrieval_version=version)
