"""可解释、权限优先的投资研究 Graph RAG。

图层只负责把已有结构化关系用于检索扩展，不创建正式业务关系，也不执行 Agentic RAG 的
任务规划、循环检索或停止决策。正式证据关系仍由服务层人工闸门控制。
"""

from __future__ import annotations

import heapq
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from itertools import count
from typing import Any

from app.ai.retrieval import (
    RetrievalDocument,
    RetrievalQuery,
    RetrievalResult,
    RetrievedChunk,
    Retriever,
    document_allowed,
    tokenize,
)

GRAPH_RAG_VERSION = "investment-graph-rag-v2-layered"


class GraphLayer(StrEnum):
    """知识库层级；数值顺序由 ``GRAPH_LAYER_RANK`` 显式定义。"""

    SOURCE = "原始证据层"
    OBSERVATION = "事实观测层"
    SEMANTIC = "领域语义层"
    RESEARCH = "投资研究层"
    SUMMARY = "聚合摘要层"


class GraphNodeKind(StrEnum):
    SECURITY = "证券"
    DOCUMENT = "文档"
    SEGMENT = "原文片段"
    EVENT = "事件"
    FACT = "事实"
    BUSINESS_VARIABLE = "业务变量"
    METRIC = "指标"
    OBSERVATION = "指标观测"
    THESIS = "投资逻辑"
    HYPOTHESIS = "投资假设"
    EVIDENCE = "证据"
    SUMMARY = "聚合摘要"


class GraphEdgeKind(StrEnum):
    HAS_THESIS = "拥有逻辑"
    HAS_HYPOTHESIS = "包含假设"
    DEPENDS_ON = "依赖变量"
    MEASURED_BY = "由指标衡量"
    HAS_OBSERVATION = "包含观测"
    DISCLOSED_IN = "披露于"
    CONTAINS = "包含片段"
    STATES_FACT = "陈述事实"
    OBSERVES = "观测指标"
    AFFECTS = "影响变量"
    DERIVED_FROM = "来源于"
    CITES = "引用原文"
    SUPPORTS = "支持"
    CHALLENGES = "冲突"
    CONTEXTUALIZES = "提供背景"
    SUMMARIZES = "汇总"


_NODE_LAYER: dict[GraphNodeKind, GraphLayer] = {
    GraphNodeKind.DOCUMENT: GraphLayer.SOURCE,
    GraphNodeKind.SEGMENT: GraphLayer.SOURCE,
    GraphNodeKind.EVENT: GraphLayer.OBSERVATION,
    GraphNodeKind.FACT: GraphLayer.OBSERVATION,
    GraphNodeKind.OBSERVATION: GraphLayer.OBSERVATION,
    GraphNodeKind.BUSINESS_VARIABLE: GraphLayer.SEMANTIC,
    GraphNodeKind.METRIC: GraphLayer.SEMANTIC,
    GraphNodeKind.SECURITY: GraphLayer.RESEARCH,
    GraphNodeKind.THESIS: GraphLayer.RESEARCH,
    GraphNodeKind.HYPOTHESIS: GraphLayer.RESEARCH,
    GraphNodeKind.EVIDENCE: GraphLayer.RESEARCH,
    GraphNodeKind.SUMMARY: GraphLayer.SUMMARY,
}

GRAPH_LAYER_RANK: dict[GraphLayer, int] = {
    GraphLayer.SOURCE: 0,
    GraphLayer.OBSERVATION: 1,
    GraphLayer.SEMANTIC: 2,
    GraphLayer.RESEARCH: 3,
    GraphLayer.SUMMARY: 4,
}


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    kind: GraphNodeKind
    label: str
    content: str = ""
    security_id: str | None = None
    published_at: datetime | None = None
    visibility_label: str | None = None
    locator: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    layer: GraphLayer | None = None

    def __post_init__(self) -> None:
        expected = _NODE_LAYER.get(self.kind)
        if self.layer is None:
            if expected is None:
                raise ValueError(f"节点类型 {self.kind.value} 尚未配置知识层")
            object.__setattr__(self, "layer", expected)
        elif expected is not None and self.layer is not expected:
            raise ValueError(
                f"节点类型 {self.kind.value} 必须位于 {expected.value}，不能位于 {self.layer.value}"
            )


@dataclass(frozen=True)
class GraphEdge:
    source_id: str
    target_id: str
    kind: GraphEdgeKind
    weight: float = 1.0
    confirmed: bool = True
    provenance_locator: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0 < self.weight <= 1:
            raise ValueError("图边权重必须在 (0, 1] 范围内")


@dataclass(frozen=True)
class GraphPath:
    node_ids: tuple[str, ...]
    edges: tuple[GraphEdge, ...]
    edge_forward: tuple[bool, ...]
    score: float

    def to_metadata(self, graph: InvestmentKnowledgeGraph) -> dict[str, Any]:
        nodes = [graph.nodes[node_id] for node_id in self.node_ids]
        explanation = nodes[0].label if nodes else ""
        for edge, forward, node in zip(self.edges, self.edge_forward, nodes[1:], strict=True):
            arrow = f"--{edge.kind.value}-->" if forward else f"<--{edge.kind.value}--"
            explanation += f" {arrow} {node.label}"
        return {
            "score": round(self.score, 8),
            "node_ids": list(self.node_ids),
            "node_kinds": [node.kind.value for node in nodes],
            "layers": [node.layer.value for node in nodes if node.layer is not None],
            "relations": [
                edge.kind.value if forward else f"反向:{edge.kind.value}"
                for edge, forward in zip(self.edges, self.edge_forward, strict=True)
            ],
            "provenance_locators": [
                edge.provenance_locator for edge in self.edges if edge.provenance_locator
            ],
            "explanation": explanation,
        }


class InvestmentKnowledgeGraph:
    """确定性内存图；事实源仍是现有关系库和版本化原文。"""

    def __init__(self) -> None:
        self.nodes: dict[str, GraphNode] = {}
        self._adjacency: dict[str, list[tuple[str, GraphEdge, bool]]] = defaultdict(list)
        self._edge_keys: set[tuple[str, str, GraphEdgeKind]] = set()
        self._edges: list[GraphEdge] = []

    def add_node(self, node: GraphNode) -> None:
        existing = self.nodes.get(node.node_id)
        if existing is None:
            self.nodes[node.node_id] = node
            return
        if existing.kind is not node.kind:
            raise ValueError(f"节点 {node.node_id} 类型冲突")
        if existing.layer is not node.layer:
            raise ValueError(f"节点 {node.node_id} 知识层冲突")
        metadata = {**existing.metadata, **node.metadata}
        self.nodes[node.node_id] = GraphNode(
            node_id=node.node_id,
            kind=node.kind,
            label=node.label or existing.label,
            content=node.content or existing.content,
            security_id=node.security_id or existing.security_id,
            published_at=node.published_at or existing.published_at,
            visibility_label=node.visibility_label or existing.visibility_label,
            locator=node.locator or existing.locator,
            metadata=metadata,
            layer=node.layer,
        )

    def add_edge(self, edge: GraphEdge) -> None:
        if edge.source_id not in self.nodes or edge.target_id not in self.nodes:
            raise ValueError("添加图边前必须先添加两端节点")
        key = (edge.source_id, edge.target_id, edge.kind)
        if key in self._edge_keys:
            return
        self._edge_keys.add(key)
        self._edges.append(edge)
        self._adjacency[edge.source_id].append((edge.target_id, edge, True))
        # 检索遍历允许反向走图，但元数据始终保留事实边的原始方向。
        self._adjacency[edge.target_id].append((edge.source_id, edge, False))

    def neighbors(self, node_id: str) -> tuple[tuple[str, GraphEdge, bool], ...]:
        return tuple(self._adjacency.get(node_id, ()))

    @property
    def edge_count(self) -> int:
        return len(self._edge_keys)

    @property
    def edges(self) -> tuple[GraphEdge, ...]:
        return tuple(self._edges)

    def layer_counts(self) -> dict[GraphLayer, int]:
        counts = {layer: 0 for layer in GraphLayer}
        for node in self.nodes.values():
            if node.layer is not None:
                counts[node.layer] += 1
        return counts


class GraphRetriever:
    """将文本召回与结构化关系路径融合为带原文引用的检索结果。"""

    def __init__(
        self,
        *,
        text_retriever: Retriever,
        graph: InvestmentKnowledgeGraph | None = None,
        text_weight: float = 0.35,
        graph_weight: float = 0.65,
        max_hops: int = 5,
        hop_decay: float = 0.82,
        candidate_multiplier: int = 4,
        max_paths_per_chunk: int = 3,
        max_expansions: int = 5000,
        include_unconfirmed_edges: bool = False,
        enforce_layer_monotonicity: bool = True,
        snapshot_metadata: dict[str, Any] | None = None,
    ) -> None:
        if text_weight < 0 or graph_weight < 0 or text_weight + graph_weight == 0:
            raise ValueError("Graph RAG 权重必须非负且至少一个大于零")
        if not 0 < hop_decay <= 1:
            raise ValueError("hop_decay 必须在 (0, 1] 范围内")
        total = text_weight + graph_weight
        self.text_weight = text_weight / total
        self.graph_weight = graph_weight / total
        self.text_retriever = text_retriever
        self.graph = graph or InvestmentKnowledgeGraph()
        self.max_hops = max(1, max_hops)
        self.hop_decay = hop_decay
        self.candidate_multiplier = max(1, candidate_multiplier)
        self.max_paths_per_chunk = max(1, max_paths_per_chunk)
        self.max_expansions = max(1, max_expansions)
        self.include_unconfirmed_edges = include_unconfirmed_edges
        self.enforce_layer_monotonicity = enforce_layer_monotonicity
        self.snapshot_metadata = dict(snapshot_metadata or {})
        self._documents: dict[str, RetrievalDocument] = {}

    @staticmethod
    def document_node_id(document_id: str) -> str:
        return f"document:{document_id}"

    @staticmethod
    def segment_node_id(locator: str) -> str:
        return f"segment:{locator}"

    def add(self, documents: list[RetrievalDocument]) -> None:
        self.text_retriever.add(documents)
        for document in documents:
            self._documents[document.locator] = document
            document_node_id = self.document_node_id(document.document_id)
            segment_node_id = self.segment_node_id(document.locator)
            self.graph.add_node(
                GraphNode(
                    node_id=document_node_id,
                    kind=GraphNodeKind.DOCUMENT,
                    label=document.source or document.document_id,
                    security_id=document.security_id,
                    published_at=document.published_at,
                    visibility_label=document.visibility_label,
                    metadata={"document_id": document.document_id},
                )
            )
            self.graph.add_node(
                GraphNode(
                    node_id=segment_node_id,
                    kind=GraphNodeKind.SEGMENT,
                    label=document.locator,
                    content=document.content,
                    security_id=document.security_id,
                    published_at=document.published_at,
                    visibility_label=document.visibility_label,
                    locator=document.locator,
                    metadata={"document_id": document.document_id},
                )
            )
            self.graph.add_edge(
                GraphEdge(document_node_id, segment_node_id, GraphEdgeKind.CONTAINS)
            )

    def search(self, query: RetrievalQuery) -> RetrievalResult:
        if query.top_k <= 0:
            return RetrievalResult(query=query, items=[], retrieval_version=GRAPH_RAG_VERSION)
        expanded = replace(query, top_k=query.top_k * self.candidate_multiplier)
        text_result = self.text_retriever.search(expanded)
        for item in text_result.items:
            self._documents.setdefault(
                item.locator,
                RetrievalDocument(
                    document_id=item.document_id,
                    security_id=item.security_id,
                    locator=item.locator,
                    content=item.content,
                    published_at=item.published_at,
                    visibility_label=item.visibility_label,
                    source=item.source,
                    metadata=dict(item.metadata),
                ),
            )

        seeds = self._seed_nodes(query, text_result.items)
        paths = self._expand_paths(query, seeds)
        text_scores = self._normalize_text_scores(text_result.items)
        graph_scores = {
            locator: max(path.score for path in locator_paths)
            for locator, locator_paths in paths.items()
        }
        version = f"{GRAPH_RAG_VERSION}[{text_result.retrieval_version}]"
        locators = set(text_scores) | set(graph_scores)
        ranked: list[RetrievedChunk] = []
        for locator in locators:
            document = self._documents.get(locator)
            if document is None or not self._document_allowed(document, query):
                continue
            score = self.text_weight * text_scores.get(
                locator, 0.0
            ) + self.graph_weight * graph_scores.get(locator, 0.0)
            metadata = dict(document.metadata)
            metadata.update(
                {
                    "retrieval_mode": "graph",
                    "retrieval_version": version,
                    "score_components": {
                        "text": round(text_scores.get(locator, 0.0), 8),
                        "graph": round(graph_scores.get(locator, 0.0), 8),
                    },
                    "graph_paths": [
                        path.to_metadata(self.graph)
                        for path in paths.get(locator, ())[: self.max_paths_per_chunk]
                    ],
                    "graph_snapshot": dict(self.snapshot_metadata),
                }
            )
            ranked.append(
                RetrievedChunk(
                    document_id=document.document_id,
                    security_id=document.security_id,
                    locator=document.locator,
                    content=document.content,
                    published_at=document.published_at,
                    visibility_label=document.visibility_label,
                    source=document.source,
                    score=round(score, 8),
                    metadata=metadata,
                )
            )
        ranked.sort(key=lambda item: (-item.score, -item.published_at.timestamp(), item.locator))
        return RetrievalResult(query=query, items=ranked[: query.top_k], retrieval_version=version)

    def _seed_nodes(
        self, query: RetrievalQuery, text_items: list[RetrievedChunk]
    ) -> dict[str, float]:
        seeds: dict[str, float] = {
            node_id: 1.0
            for node_id in query.seed_node_ids
            if node_id in self.graph.nodes and self._node_allowed(self.graph.nodes[node_id], query)
        }
        query_tokens = tokenize(query.text)
        for node in self.graph.nodes.values():
            if not self._node_allowed(node, query):
                continue
            overlap = query_tokens & tokenize(f"{node.label} {node.content}")
            if overlap:
                seeds[node.node_id] = max(
                    seeds.get(node.node_id, 0.0), len(overlap) / max(len(query_tokens), 1)
                )
        for rank, item in enumerate(text_items, start=1):
            node_id = self.segment_node_id(item.locator)
            if node_id in self.graph.nodes:
                seeds[node_id] = max(seeds.get(node_id, 0.0), 1 / rank)
        return seeds

    def _expand_paths(
        self, query: RetrievalQuery, seeds: dict[str, float]
    ) -> dict[str, list[GraphPath]]:
        found: dict[str, list[GraphPath]] = defaultdict(list)
        queue: list[
            tuple[
                float,
                int,
                int,
                tuple[str, ...],
                tuple[GraphEdge, ...],
                tuple[bool, ...],
                int,
            ]
        ] = []
        serial = count()
        for node_id, score in seeds.items():
            heapq.heappush(queue, (-score, 0, next(serial), (node_id,), (), (), 0))
        best: dict[tuple[str, str, int], float] = {}
        expansions = 0
        while queue and expansions < self.max_expansions:
            negative_score, hops, _, node_ids, edges, directions, layer_direction = heapq.heappop(
                queue
            )
            score = -negative_score
            node_id = node_ids[-1]
            seed_id = node_ids[0]
            if score + 1e-12 < best.get((seed_id, node_id, layer_direction), -1.0):
                continue
            best[(seed_id, node_id, layer_direction)] = score
            node = self.graph.nodes[node_id]
            if (
                node.kind is GraphNodeKind.SEGMENT
                and node.locator
                and node.locator in self._documents
            ):
                found[node.locator].append(GraphPath(node_ids, edges, directions, score))
                found[node.locator].sort(key=lambda path: -path.score)
                del found[node.locator][self.max_paths_per_chunk :]
            if hops >= self.max_hops:
                continue
            for neighbor_id, edge, forward in self.graph.neighbors(node_id):
                expansions += 1
                if neighbor_id in node_ids:
                    continue
                if not edge.confirmed and not self.include_unconfirmed_edges:
                    continue
                neighbor = self.graph.nodes[neighbor_id]
                if not self._node_allowed(neighbor, query):
                    continue
                next_layer_direction = self._next_layer_direction(node, neighbor, layer_direction)
                if next_layer_direction is None:
                    continue
                next_score = score * edge.weight * self.hop_decay
                if next_score <= best.get((seed_id, neighbor_id, next_layer_direction), -1.0):
                    continue
                heapq.heappush(
                    queue,
                    (
                        -next_score,
                        hops + 1,
                        next(serial),
                        (*node_ids, neighbor_id),
                        (*edges, edge),
                        (*directions, forward),
                        next_layer_direction,
                    ),
                )
        return found

    def _next_layer_direction(
        self,
        current: GraphNode,
        neighbor: GraphNode,
        direction: int,
    ) -> int | None:
        """限制一条路径只能持续上钻或下钻，避免跨层后折返形成语义捷径。"""

        if not self.enforce_layer_monotonicity:
            return direction
        if current.layer is None or neighbor.layer is None:
            return direction
        step = GRAPH_LAYER_RANK[neighbor.layer] - GRAPH_LAYER_RANK[current.layer]
        if step == 0:
            return direction
        step_direction = 1 if step > 0 else -1
        if direction and direction != step_direction:
            return None
        return step_direction

    @staticmethod
    def _normalize_text_scores(items: list[RetrievedChunk]) -> dict[str, float]:
        if not items:
            return {}
        maximum = max((item.score for item in items), default=0.0)
        if maximum <= 0:
            return {item.locator: 1 / rank for rank, item in enumerate(items, start=1)}
        return {item.locator: max(item.score, 0.0) / maximum for item in items}

    @staticmethod
    def _document_allowed(document: RetrievalDocument, query: RetrievalQuery) -> bool:
        return document_allowed(document, query)

    @staticmethod
    def _node_allowed(node: GraphNode, query: RetrievalQuery) -> bool:
        document_id = str(node.metadata.get("document_id") or "")
        if (
            query.allowed_document_ids is not None
            and document_id
            and document_id not in query.allowed_document_ids
        ):
            return False
        if query.security_id and node.security_id and node.security_id != query.security_id:
            return False
        if node.visibility_label and node.visibility_label not in query.allowed_visibility:
            return False
        return not (query.as_of and node.published_at and node.published_at > query.as_of)


class RankStableGraphAssistRetriever:
    """保留文本候选顺序，同时附加可审计图路径并在文本不足时回填。

    这是产品默认的 Graph 辅助策略：Graph 不抢占文本 Top-K 排名，避免在尚未证明
    全量重排稳定性时改变研究员看到的首要证据；但每条同候选图命中都会携带路径、
    分数组件和快照，文本召回不足时才追加有图路径的候选。
    """

    retrieval_version = "graph-assist-rank-stable-v1"

    def __init__(
        self,
        *,
        text_retriever: Retriever,
        graph_retriever: Retriever,
        candidate_multiplier: int = 3,
    ) -> None:
        self.text_retriever = text_retriever
        self.graph_retriever = graph_retriever
        self.candidate_multiplier = max(1, candidate_multiplier)

    def add(self, documents: list[RetrievalDocument]) -> None:
        self.text_retriever.add(documents)
        self.graph_retriever.add(documents)

    def search(self, query: RetrievalQuery) -> RetrievalResult:
        if query.top_k <= 0:
            return RetrievalResult(query=query, items=[], retrieval_version=self.retrieval_version)
        expanded = replace(query, top_k=query.top_k * self.candidate_multiplier)
        text_result = self.text_retriever.search(expanded)
        graph_result = self.graph_retriever.search(expanded)
        graph_by_locator = {item.locator: item for item in graph_result.items}
        merged: list[RetrievedChunk] = []
        seen: set[str] = set()
        for text_rank, item in enumerate(text_result.items[: query.top_k], start=1):
            graph_item = graph_by_locator.get(item.locator)
            metadata = dict(item.metadata)
            if graph_item is not None:
                for key in ("score_components", "graph_paths", "graph_snapshot"):
                    if key in graph_item.metadata:
                        metadata[key] = graph_item.metadata[key]
                metadata.update(
                    {
                        "retrieval_mode": "graph_assist",
                        "graph_assist_action": "rank_preserved",
                        "graph_score": graph_item.score,
                        "text_rank": text_rank,
                    }
                )
            else:
                metadata.update(
                    {
                        "retrieval_mode": "text_fallback",
                        "graph_assist_action": "no_graph_path",
                        "graph_paths": [],
                        "text_rank": text_rank,
                    }
                )
            merged.append(replace(item, metadata=metadata))
            seen.add(item.locator)

        if len(merged) < query.top_k:
            for graph_item in graph_result.items:
                if graph_item.locator in seen or not graph_item.metadata.get("graph_paths"):
                    continue
                merged.append(
                    replace(
                        graph_item,
                        metadata={
                            **graph_item.metadata,
                            "retrieval_mode": "graph_assist",
                            "graph_assist_action": "graph_backfill",
                        },
                    )
                )
                seen.add(graph_item.locator)
                if len(merged) >= query.top_k:
                    break

        version = (
            f"{self.retrieval_version}[text={text_result.retrieval_version}]"
            f"[graph={graph_result.retrieval_version}]"
        )
        return RetrievalResult(query=query, items=merged, retrieval_version=version)


class EvidenceFusionGraphRetriever:
    """用确定性 RRF 融合词面、中文 BM25 与 Graph 路径排序。

    Graph 是主排序分支；文本分支用于抵抗图投影遗漏。财报类披露拥有固定、可审计的
    高证据密度先验，但仍必须先通过候选池、证券、权限和时间过滤。该排序器不读取
    相关性标签，也不改变 Graph 路径与原文引用。
    """

    retrieval_version = "graph-evidence-fusion-v1[rrf_k=1,text=0.25,bm25=0.5,graph=1,report=1]"
    _HIGH_EVIDENCE_DISCLOSURE_TERMS = (
        "年度报告",
        "季度报告",
        "中期业绩",
        "全年业绩",
        "财务业绩",
        "年度业绩",
    )

    def __init__(
        self,
        *,
        text_retriever: Retriever,
        bm25_retriever: Retriever,
        graph_retriever: Retriever,
        text_weight: float = 0.25,
        bm25_weight: float = 0.5,
        graph_weight: float = 1.0,
        report_prior_weight: float = 1.0,
        rrf_k: int = 1,
        candidate_multiplier: int = 3,
    ) -> None:
        if min(text_weight, bm25_weight, graph_weight, report_prior_weight) < 0:
            raise ValueError("证据融合权重必须非负")
        if text_weight + bm25_weight + graph_weight == 0:
            raise ValueError("证据融合至少需要一个检索分支")
        self.text_retriever = text_retriever
        self.bm25_retriever = bm25_retriever
        self.graph_retriever = graph_retriever
        self.text_weight = text_weight
        self.bm25_weight = bm25_weight
        self.graph_weight = graph_weight
        self.report_prior_weight = report_prior_weight
        self.rrf_k = max(1, rrf_k)
        self.candidate_multiplier = max(1, candidate_multiplier)

    def add(self, documents: list[RetrievalDocument]) -> None:
        self.text_retriever.add(documents)
        if self.bm25_retriever is not self.text_retriever:
            self.bm25_retriever.add(documents)
        self.graph_retriever.add(documents)

    def search(self, query: RetrievalQuery) -> RetrievalResult:
        if query.top_k <= 0:
            return RetrievalResult(query=query, items=[], retrieval_version=self.retrieval_version)
        expanded = replace(query, top_k=query.top_k * self.candidate_multiplier)
        branch_results = (
            ("text", self.text_weight, self.text_retriever.search(expanded)),
            ("bm25", self.bm25_weight, self.bm25_retriever.search(expanded)),
            ("graph", self.graph_weight, self.graph_retriever.search(expanded)),
        )
        scores: dict[str, float] = defaultdict(float)
        ranks: dict[str, dict[str, int]] = defaultdict(dict)
        chunks: dict[str, RetrievedChunk] = {}
        graph_chunks: dict[str, RetrievedChunk] = {}
        for branch, weight, result in branch_results:
            for rank, item in enumerate(result.items, start=1):
                chunks.setdefault(item.locator, item)
                if branch == "graph":
                    graph_chunks[item.locator] = item
                ranks[item.locator][branch] = rank
                scores[item.locator] += weight / (self.rrf_k + rank)

        for locator, item in chunks.items():
            if any(term in (item.source or "") for term in self._HIGH_EVIDENCE_DISCLOSURE_TERMS):
                scores[locator] += self.report_prior_weight / (self.rrf_k + 1)

        ranked: list[RetrievedChunk] = []
        for locator, item in chunks.items():
            preferred = graph_chunks.get(locator, item)
            report_prior = (
                self.report_prior_weight / (self.rrf_k + 1)
                if any(
                    term in (preferred.source or "")
                    for term in self._HIGH_EVIDENCE_DISCLOSURE_TERMS
                )
                else 0.0
            )
            ranked.append(
                replace(
                    preferred,
                    score=round(scores[locator], 8),
                    metadata={
                        **preferred.metadata,
                        "retrieval_mode": "graph_evidence_fusion",
                        "evidence_fusion": {
                            "branch_ranks": dict(ranks[locator]),
                            "weights": {
                                "text": self.text_weight,
                                "bm25": self.bm25_weight,
                                "graph": self.graph_weight,
                            },
                            "rrf_k": self.rrf_k,
                            "report_prior": round(report_prior, 8),
                        },
                    },
                )
            )
        ranked.sort(key=lambda item: (-item.score, -item.published_at.timestamp(), item.locator))
        versions = "+".join(result.retrieval_version for _, _, result in branch_results)
        return RetrievalResult(
            query=query,
            items=ranked[: query.top_k],
            retrieval_version=f"{self.retrieval_version}[{versions}]",
        )
