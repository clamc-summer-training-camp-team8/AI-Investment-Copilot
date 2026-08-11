from __future__ import annotations

from datetime import datetime, timezone

from app.ai.retrieval import KeywordRetriever, RetrievalDocument, RetrievalQuery


def _dt(day: int) -> datetime:
    return datetime(2026, 8, day, tzinfo=timezone.utc)


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
