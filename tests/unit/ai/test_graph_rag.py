from __future__ import annotations

from datetime import UTC, datetime

from app.ai.graph_rag import (
    GRAPH_RAG_VERSION,
    EvidenceFusionGraphRetriever,
    GraphEdge,
    GraphEdgeKind,
    GraphLayer,
    GraphNode,
    GraphNodeKind,
    GraphRetriever,
    InvestmentKnowledgeGraph,
    RankStableGraphAssistRetriever,
)
from app.ai.retrieval import BM25Retriever, KeywordRetriever, RetrievalDocument, RetrievalQuery


def _dt(day: int) -> datetime:
    return datetime(2026, 8, day, tzinfo=UTC)


def _graph_retriever(*, visibility: str = "公开", published_at: datetime | None = None):
    graph = InvestmentKnowledgeGraph()
    retriever = GraphRetriever(text_retriever=KeywordRetriever(), graph=graph, max_hops=5)
    document = RetrievalDocument(
        document_id="DOC-1",
        security_id="688981",
        locator="DOC-1#paragraph-7",
        content="本季度晶圆出货九百七十万片。",
        published_at=published_at or _dt(2),
        visibility_label=visibility,
        source="季度报告",
    )
    retriever.add([document])
    graph.add_node(
        GraphNode(
            "hypothesis:H1",
            GraphNodeKind.HYPOTHESIS,
            "需求与出货保持增长",
            security_id="688981",
        )
    )
    graph.add_node(
        GraphNode(
            "variable:demand",
            GraphNodeKind.BUSINESS_VARIABLE,
            "需求与出货",
            security_id="688981",
        )
    )
    graph.add_node(GraphNode("metric:shipments", GraphNodeKind.METRIC, "晶圆出货量"))
    graph.add_node(
        GraphNode(
            "fact:F1",
            GraphNodeKind.FACT,
            "晶圆出货量",
            content="九百七十万片",
            security_id="688981",
            published_at=published_at or _dt(2),
            visibility_label=visibility,
            locator=document.locator,
        )
    )
    graph.add_edge(GraphEdge("hypothesis:H1", "variable:demand", GraphEdgeKind.DEPENDS_ON))
    graph.add_edge(GraphEdge("variable:demand", "metric:shipments", GraphEdgeKind.MEASURED_BY))
    graph.add_edge(GraphEdge("fact:F1", "metric:shipments", GraphEdgeKind.OBSERVES))
    graph.add_edge(
        GraphEdge(
            retriever.segment_node_id(document.locator),
            "fact:F1",
            GraphEdgeKind.STATES_FACT,
            provenance_locator=document.locator,
        )
    )
    return retriever


def test_graph_rag_通过业务关系召回文本不重合的原文() -> None:
    retriever = _graph_retriever()

    result = retriever.search(
        RetrievalQuery(
            text="需求假设",
            security_id="688981",
            as_of=_dt(10),
            top_k=3,
            seed_node_ids=frozenset({"hypothesis:H1"}),
        )
    )

    assert [item.locator for item in result.items] == ["DOC-1#paragraph-7"]
    assert result.items[0].metadata["score_components"]["text"] == 0
    assert result.items[0].metadata["score_components"]["graph"] > 0
    path = result.items[0].metadata["graph_paths"][0]
    assert path["node_kinds"] == ["投资假设", "业务变量", "指标", "事实", "原文片段"]
    assert path["layers"] == [
        "投资研究层",
        "领域语义层",
        "领域语义层",
        "事实观测层",
        "原始证据层",
    ]
    assert "反向:观测指标" in path["relations"]
    assert path["provenance_locators"] == ["DOC-1#paragraph-7"]
    assert GRAPH_RAG_VERSION in result.retrieval_version


def test_graph_rag_整条路径执行权限与时间过滤() -> None:
    restricted = _graph_retriever(visibility="内部受限")
    future = _graph_retriever(published_at=_dt(20))
    query = RetrievalQuery(
        text="需求假设",
        security_id="688981",
        as_of=_dt(10),
        allowed_visibility=frozenset({"公开"}),
        seed_node_ids=frozenset({"hypothesis:H1"}),
    )

    assert restricted.search(query).items == []
    assert future.search(query).items == []


def test_graph_rag_候选池约束阻止图路径越界扩展() -> None:
    retriever = _graph_retriever()

    result = retriever.search(
        RetrievalQuery(
            text="需求假设",
            security_id="688981",
            allowed_document_ids=frozenset(),
            seed_node_ids=frozenset({"hypothesis:H1"}),
        )
    )

    assert result.items == []


def test_graph_assist_保留文本顺序并只用图路径回填缺口() -> None:
    text = KeywordRetriever()
    graph = InvestmentKnowledgeGraph()
    graph_retriever = GraphRetriever(text_retriever=KeywordRetriever(), graph=graph)
    assist = RankStableGraphAssistRetriever(
        text_retriever=text,
        graph_retriever=graph_retriever,
    )
    documents = [
        RetrievalDocument("DOC-TEXT", "688981", "DOC-TEXT#p1", "需求增长", _dt(2)),
        RetrievalDocument("DOC-GRAPH", "688981", "DOC-GRAPH#p1", "无词面重合", _dt(1)),
    ]
    assist.add(documents)
    graph.add_node(
        GraphNode("hypothesis:H3", GraphNodeKind.HYPOTHESIS, "需求", security_id="688981")
    )
    graph.add_edge(
        GraphEdge(
            "hypothesis:H3",
            graph_retriever.segment_node_id("DOC-GRAPH#p1"),
            GraphEdgeKind.CITES,
            provenance_locator="DOC-GRAPH#p1",
        )
    )

    result = assist.search(
        RetrievalQuery(
            text="需求增长",
            security_id="688981",
            top_k=2,
            seed_node_ids=frozenset({"hypothesis:H3"}),
        )
    )

    assert [item.document_id for item in result.items] == ["DOC-TEXT", "DOC-GRAPH"]
    assert result.items[0].metadata["graph_assist_action"] == "rank_preserved"
    assert result.items[1].metadata["graph_assist_action"] == "graph_backfill"
    assert result.items[1].metadata["graph_paths"]


def test_graph_evidence_fusion_融合多路排序并保留图路径() -> None:
    graph = InvestmentKnowledgeGraph()
    graph_retriever = GraphRetriever(text_retriever=KeywordRetriever(), graph=graph)
    fusion = EvidenceFusionGraphRetriever(
        text_retriever=KeywordRetriever(),
        bm25_retriever=BM25Retriever(),
        graph_retriever=graph_retriever,
    )
    documents = [
        RetrievalDocument(
            "DOC-NOTICE",
            "688981",
            "DOC-NOTICE#p1",
            "成本改善",
            _dt(3),
            source="临时公告",
        ),
        RetrievalDocument(
            "DOC-REPORT",
            "688981",
            "DOC-REPORT#p1",
            "成本改善",
            _dt(2),
            source="2025年年度报告",
        ),
    ]
    fusion.add(documents)
    graph.add_node(
        GraphNode("hypothesis:H4", GraphNodeKind.HYPOTHESIS, "成本改善", security_id="688981")
    )
    graph.add_edge(
        GraphEdge(
            "hypothesis:H4",
            graph_retriever.segment_node_id("DOC-REPORT#p1"),
            GraphEdgeKind.CITES,
            provenance_locator="DOC-REPORT#p1",
        )
    )

    result = fusion.search(
        RetrievalQuery(
            text="成本改善",
            security_id="688981",
            top_k=2,
            seed_node_ids=frozenset({"hypothesis:H4"}),
        )
    )

    assert [item.document_id for item in result.items] == ["DOC-REPORT", "DOC-NOTICE"]
    assert result.items[0].metadata["retrieval_mode"] == "graph_evidence_fusion"
    assert result.items[0].metadata["evidence_fusion"]["report_prior"] == 0.5
    assert result.items[0].metadata["graph_paths"]


def test_graph_rag_默认不沿未确认关系扩展() -> None:
    graph = InvestmentKnowledgeGraph()
    retriever = GraphRetriever(text_retriever=KeywordRetriever(), graph=graph)
    document = RetrievalDocument(
        "DOC-2",
        "688981",
        "DOC-2#paragraph-1",
        "候选资料",
        _dt(1),
    )
    retriever.add([document])
    graph.add_node(
        GraphNode("hypothesis:H2", GraphNodeKind.HYPOTHESIS, "盈利假设", security_id="688981")
    )
    graph.add_edge(
        GraphEdge(
            "hypothesis:H2",
            retriever.segment_node_id(document.locator),
            GraphEdgeKind.CITES,
            confirmed=False,
        )
    )

    result = retriever.search(
        RetrievalQuery(
            text="盈利假设",
            security_id="688981",
            seed_node_ids=frozenset({"hypothesis:H2"}),
        )
    )

    assert result.items == []


def test_graph_rag_节点类型自动映射到显式知识层() -> None:
    assert GraphNode("segment:S1", GraphNodeKind.SEGMENT, "原文").layer is GraphLayer.SOURCE
    assert GraphNode("fact:F1", GraphNodeKind.FACT, "事实").layer is GraphLayer.OBSERVATION
    assert GraphNode("metric:M1", GraphNodeKind.METRIC, "指标").layer is GraphLayer.SEMANTIC
    assert GraphNode("hypothesis:H1", GraphNodeKind.HYPOTHESIS, "假设").layer is GraphLayer.RESEARCH


def test_graph_rag_分层遍历禁止下钻后再上钻形成捷径() -> None:
    graph = InvestmentKnowledgeGraph()
    retriever = GraphRetriever(text_retriever=KeywordRetriever(), graph=graph, max_hops=4)
    document = RetrievalDocument(
        "DOC-ZIGZAG",
        "688981",
        "DOC-ZIGZAG#paragraph-1",
        "gamma_evidence",
        _dt(1),
    )
    retriever.add([document])
    graph.add_node(
        GraphNode("hypothesis:H1", GraphNodeKind.HYPOTHESIS, "alpha_seed", security_id="688981")
    )
    graph.add_node(
        GraphNode("hypothesis:H2", GraphNodeKind.HYPOTHESIS, "beta_node", security_id="688981")
    )
    graph.add_node(GraphNode("metric:M1", GraphNodeKind.METRIC, "shared_metric"))
    graph.add_edge(GraphEdge("hypothesis:H1", "metric:M1", GraphEdgeKind.MEASURED_BY))
    graph.add_edge(GraphEdge("hypothesis:H2", "metric:M1", GraphEdgeKind.MEASURED_BY))
    graph.add_edge(
        GraphEdge(
            "hypothesis:H2",
            retriever.segment_node_id(document.locator),
            GraphEdgeKind.CITES,
        )
    )

    result = retriever.search(
        RetrievalQuery(
            text="alpha_seed",
            security_id="688981",
            seed_node_ids=frozenset({"hypothesis:H1"}),
        )
    )

    assert result.items == []
