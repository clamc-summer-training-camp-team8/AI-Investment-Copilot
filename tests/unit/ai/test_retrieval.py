from __future__ import annotations

from datetime import UTC, datetime

from app.ai.retrieval import (
    AnnouncementTypePriorRetriever,
    BM25Retriever,
    ChineseVectorRetriever,
    DiversityReranker,
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


def test_retriever_候选池约束与证券权限时间共同生效() -> None:
    retriever = KeywordRetriever()
    retriever.add(
        [
            RetrievalDocument(
                document_id=document_id,
                security_id="000538.SZ",
                locator=f"{document_id}#paragraph-1",
                content="核心业务收入增长",
                published_at=_dt(1),
            )
            for document_id in ("DOC-ALLOW", "DOC-OUTSIDE")
        ]
    )

    result = retriever.search(
        RetrievalQuery(
            text="核心业务收入增长",
            security_id="000538.SZ",
            allowed_document_ids=frozenset({"DOC-ALLOW"}),
        )
    )

    assert [item.document_id for item in result.items] == ["DOC-ALLOW"]
    assert (
        retriever.search(
            RetrievalQuery(
                text="核心业务收入增长",
                security_id="000538.SZ",
                allowed_document_ids=frozenset(),
            )
        ).items
        == []
    )


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


def test_bm25_and_chinese_vector_retrieval_keep_security_time_and_permission_filters() -> None:
    documents = [
        RetrievalDocument(
            "doc-public",
            "688981",
            "doc-public#paragraph-1",
            "晶圆出货量和产能利用率持续回升",
            _dt(1),
            source="季度经营数据",
        ),
        RetrievalDocument(
            "doc-private",
            "688981",
            "doc-private#paragraph-1",
            "晶圆出货量和产能利用率持续回升",
            _dt(1),
            visibility_label="内部受限",
        ),
        RetrievalDocument(
            "doc-other",
            "002594",
            "doc-other#paragraph-1",
            "晶圆出货量和产能利用率持续回升",
            _dt(1),
        ),
    ]
    query = RetrievalQuery(text="晶圆产能利用率回升", security_id="688981", as_of=_dt(10))

    for retriever in (BM25Retriever(), ChineseVectorRetriever()):
        retriever.add(documents)
        result = retriever.search(query)
        assert [item.locator for item in result.items] == ["doc-public#paragraph-1"]
        assert result.items[0].score > 0


def test_announcement_prior_demotes_governance_hard_negative_for_operating_query() -> None:
    operating = RetrievedChunk(
        "doc-operation",
        "688981",
        "doc-operation#paragraph-1",
        "营业收入与毛利率回升",
        _dt(1),
        "公开",
        "2025年年度报告",
        0.8,
    )
    governance = RetrievedChunk(
        "doc-governance",
        "688981",
        "doc-governance#paragraph-1",
        "董事会审议事项",
        _dt(2),
        "公开",
        "董事会决议公告",
        1.0,
    )
    retriever = AnnouncementTypePriorRetriever(_FixedRetriever([governance, operating], "fixed"))

    result = retriever.search(RetrievalQuery(text="毛利率持续改善", security_id="688981"))

    assert [item.document_id for item in result.items] == ["doc-operation", "doc-governance"]
    assert result.items[1].metadata["announcement_type_reason"] == "governance_hard_negative"


def test_diversity_reranker_places_distinct_disclosure_before_near_duplicate() -> None:
    first = RetrievedChunk(
        "doc-1", "688981", "doc-1#p1", "经营数据一", _dt(3), "公开", "月度经营数据公告", 1.0
    )
    duplicate = RetrievedChunk(
        "doc-2", "688981", "doc-2#p1", "经营数据二", _dt(2), "公开", "月度经营数据公告", 0.95
    )
    distinct = RetrievedChunk(
        "doc-3", "688981", "doc-3#p1", "财务数据", _dt(1), "公开", "年度报告", 0.9
    )
    retriever = DiversityReranker(_FixedRetriever([first, duplicate, distinct], "fixed"))

    result = retriever.search(RetrievalQuery(text="经营与财务", top_k=3))

    assert [item.document_id for item in result.items] == ["doc-1", "doc-3", "doc-2"]
