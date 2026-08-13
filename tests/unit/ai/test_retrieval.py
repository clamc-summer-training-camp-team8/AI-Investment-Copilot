from __future__ import annotations

from datetime import UTC, datetime

from app.ai.retrieval import (
    HybridRetriever,
    KeywordRetriever,
    RetrievalDocument,
    RetrievalQuery,
    RetrievalResult,
    RetrievedChunk,
)


def _dt(day: int) -> datetime:
    return datetime(2026, 8, day, tzinfo=UTC)


def test_retriever_按证券和时间过滤并返回引用() -> None:
    retriever = KeywordRetriever()
    retriever.add(
        [
            RetrievalDocument(
                document_id="doc-old",
                security_id="000538.SZ",
                locator="doc-old#paragraph-1",
                content="核心业务收入保持增长。",
                published_at=_dt(1),
                source="cninfo",
            ),
            RetrievalDocument(
                document_id="doc-future",
                security_id="000538.SZ",
                locator="doc-future#paragraph-1",
                content="核心业务收入保持增长。",
                published_at=_dt(20),
                source="cninfo",
            ),
            RetrievalDocument(
                document_id="doc-other",
                security_id="600000.SH",
                locator="doc-other#paragraph-1",
                content="核心业务收入保持增长。",
                published_at=_dt(1),
                source="cninfo",
            ),
        ]
    )

    result = retriever.search(
        RetrievalQuery(
            text="核心业务收入增长",
            security_id="000538.SZ",
            as_of=_dt(10),
        )
    )

    assert [item.locator for item in result.items] == ["doc-old#paragraph-1"]
    assert result.items[0].source == "cninfo"
    assert result.items[0].score > 0


def test_retriever_不返回未授权资料() -> None:
    retriever = KeywordRetriever()
    retriever.add(
        [
            RetrievalDocument(
                document_id="doc-private",
                security_id="000538.SZ",
                locator="doc-private#paragraph-1",
                content="海外订单明显增长。",
                published_at=_dt(1),
                visibility_label="内部受限",
            )
        ]
    )

    result = retriever.search(
        RetrievalQuery(
            text="海外订单增长",
            security_id="000538.SZ",
            allowed_visibility=frozenset({"公开"}),
        )
    )

    assert result.items == []


class _FixedRetriever:
    def __init__(self, items: list[RetrievedChunk], version: str) -> None:
        self.items = items
        self.version = version

    def add(self, documents: list[RetrievalDocument]) -> None:
        return None

    def search(self, query: RetrievalQuery) -> RetrievalResult:
        return RetrievalResult(query=query, items=self.items, retrieval_version=self.version)


def test_hybrid_retriever_merges_two_rankings_and_rechecks_filters() -> None:
    lexical_item = RetrievedChunk(
        "doc-lexical",
        "000538.SZ",
        "doc-lexical#paragraph-1",
        "收入增长",
        _dt(1),
        "公开",
        "cninfo",
        0.9,
    )
    vector_item = RetrievedChunk(
        "doc-vector",
        "000538.SZ",
        "doc-vector#paragraph-1",
        "经营改善",
        _dt(2),
        "公开",
        "cninfo",
        0.8,
    )
    forbidden_item = RetrievedChunk(
        "doc-private",
        "000538.SZ",
        "doc-private#paragraph-1",
        "内部资料",
        _dt(2),
        "内部受限",
        "internal",
        1.0,
    )
    retriever = HybridRetriever(
        lexical=_FixedRetriever([lexical_item], "keyword-test"),
        vector=_FixedRetriever([forbidden_item, vector_item], "vector-test"),
    )

    result = retriever.search(RetrievalQuery(text="收入改善", security_id="000538.SZ", top_k=2))

    assert {item.locator for item in result.items} == {
        "doc-lexical#paragraph-1",
        "doc-vector#paragraph-1",
    }
    assert "hybrid-v1" in result.retrieval_version
    assert all(item.score > 0 for item in result.items)
