"""从正式领域对象构建 Graph RAG 只读语料。

关系库仍是事实源。本模块仅把研究员可见且通过人工闸门的对象投影为内存图，不写数据库，
也不把候选关系升级为正式关系。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from app.ai.graph_rag import (
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
from app.ai.retrieval import BM25Retriever, RetrievalDocument, Retriever
from app.core.domain import EvidenceRecord, UnitOfWork
from app.core.enums import ConfirmationStatus, ImpactDirection

_NORMALIZE_RE = re.compile(r"[^a-z0-9\u4e00-\u9fff]+")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
GRAPH_SCHEMA_VERSION = "investment-knowledge-layers-v2"
GRAPH_BUILDER_VERSION = "layered-corpus-builder-v1"

DEFAULT_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "营业收入": ("营收", "收入", "revenue"),
    "出货量": ("销量", "出货", "shipments"),
    "平均销售价格": ("平均售价", "asp", "average selling price"),
    "毛利率": ("gross margin",),
    "订单量": ("订单", "orders"),
    "产能利用率": ("稼动率", "capacity utilization"),
}


@dataclass(frozen=True)
class MetricVocabulary:
    """受控指标别名表；只负责确定性标准化，不让模型在建图时创造关系。"""

    aliases: Mapping[str, tuple[str, ...]]
    version: str = "metric-aliases-v1"

    def canonical(self, value: str) -> str:
        normalized = _normalized(value)
        matches: list[tuple[int, str]] = []
        for canonical, aliases in self.aliases.items():
            terms = {_normalized(canonical), *(_normalized(alias) for alias in aliases)}
            for term in terms:
                if term and (term in normalized or normalized in term):
                    matches.append((len(term), _normalized(canonical)))
        if not matches:
            return normalized
        return max(matches)[1]

    def matches(self, left: str, right: str) -> bool:
        canonical_left = self.canonical(left)
        canonical_right = self.canonical(right)
        return bool(canonical_left) and (
            canonical_left == canonical_right
            or canonical_left in canonical_right
            or canonical_right in canonical_left
        )


DEFAULT_METRIC_VOCABULARY = MetricVocabulary(DEFAULT_METRIC_ALIASES)


@dataclass(frozen=True)
class GraphLayerSnapshot:
    layer: GraphLayer
    node_count: int
    content_hash: str


@dataclass(frozen=True)
class GraphSnapshot:
    """一次可复现图投影的清单，供缓存、审计和后续增量构建比较。"""

    snapshot_id: str
    schema_version: str
    builder_version: str
    vocabulary_version: str
    built_at: datetime
    as_of: datetime | None
    include_pending: bool
    thesis_ids: tuple[str, ...]
    security_ids: tuple[str, ...]
    layers: tuple[GraphLayerSnapshot, ...]


@dataclass(frozen=True)
class GraphRagCorpus:
    graph: InvestmentKnowledgeGraph
    documents: tuple[RetrievalDocument, ...]
    thesis_ids: tuple[str, ...]
    snapshot: GraphSnapshot


def _node_id(kind: GraphNodeKind, object_id: str) -> str:
    return f"{kind.name.lower()}:{object_id}"


def _variable_id(security_id: str, label: str) -> str:
    digest = sha256(f"{security_id}|{label}".encode()).hexdigest()[:16]
    return _node_id(GraphNodeKind.BUSINESS_VARIABLE, digest)


def _normalized(value: str) -> str:
    return _NORMALIZE_RE.sub("", value.lower())


def _direction_edge(direction: ImpactDirection) -> GraphEdgeKind:
    if direction is ImpactDirection.SUPPORT:
        return GraphEdgeKind.SUPPORTS
    if direction is ImpactDirection.CONFLICT:
        return GraphEdgeKind.CHALLENGES
    return GraphEdgeKind.CONTEXTUALIZES


class _ResearchLayerBuilder:
    def __init__(self, corpus: _CorpusBuilder) -> None:
        self.corpus = corpus

    def add_thesis(self, thesis_id: str) -> bool:
        return self.corpus._project_thesis(thesis_id)

    def add_evidence(self, thesis_id: str, security_id: str) -> None:
        self.corpus._project_evidence(thesis_id, security_id)


class _SemanticLayerBuilder:
    def __init__(self, corpus: _CorpusBuilder) -> None:
        self.corpus = corpus

    def matching_metric_nodes(self, fact_metric: str) -> list[str]:
        return self.corpus._matching_metric_nodes(fact_metric)


class _ObservationLayerBuilder:
    def __init__(self, corpus: _CorpusBuilder) -> None:
        self.corpus = corpus

    def add_evidence_chain(self, thesis_id: str, security_id: str) -> None:
        """投影经研究层确认的证据以及它连接的事件观测。"""

        self.corpus.research_layer.add_evidence(thesis_id, security_id)


class _SourceLayerBuilder:
    def __init__(self, corpus: _CorpusBuilder) -> None:
        self.corpus = corpus

    def add_document(self, document_id: str, *, fallback_security: str) -> str | None:
        return self.corpus._project_document(document_id, fallback_security=fallback_security)


class _CorpusBuilder:
    """按研究层→语义层→观测层→来源层的依赖顺序构建统一图投影。"""

    def __init__(
        self,
        uow: UnitOfWork,
        *,
        include_pending: bool,
        as_of: datetime | None,
        metric_vocabulary: MetricVocabulary,
    ) -> None:
        self.uow = uow
        self.include_pending = include_pending
        self.as_of = as_of
        self.metric_vocabulary = metric_vocabulary
        self.graph = InvestmentKnowledgeGraph()
        self.documents: dict[str, RetrievalDocument] = {}
        self._loaded_documents: set[str] = set()
        self._metric_nodes: dict[tuple[str, str], str] = {}
        self._metric_variables: dict[str, set[str]] = {}
        self.research_layer = _ResearchLayerBuilder(self)
        self.semantic_layer = _SemanticLayerBuilder(self)
        self.observation_layer = _ObservationLayerBuilder(self)
        self.source_layer = _SourceLayerBuilder(self)

    def add_thesis(self, thesis_id: str) -> bool:
        return self.research_layer.add_thesis(thesis_id)

    def _project_thesis(self, thesis_id: str) -> bool:
        thesis = self.uow.thesis.get(thesis_id)
        if thesis is None:
            return False
        security = self.uow.securities.get(thesis.security_id)
        security_node_id = _node_id(GraphNodeKind.SECURITY, thesis.security_id)
        self.graph.add_node(
            GraphNode(
                security_node_id,
                GraphNodeKind.SECURITY,
                security.name if security else thesis.security_id,
                security_id=thesis.security_id,
            )
        )
        thesis_node_id = _node_id(GraphNodeKind.THESIS, thesis.thesis_id)
        self.graph.add_node(
            GraphNode(
                thesis_node_id,
                GraphNodeKind.THESIS,
                thesis.title,
                content=thesis.core_view,
                security_id=thesis.security_id,
                metadata={"status": thesis.status.value, "version": thesis.version},
            )
        )
        self.graph.add_edge(GraphEdge(security_node_id, thesis_node_id, GraphEdgeKind.HAS_THESIS))
        hypotheses = self.uow.thesis.list_hypotheses(thesis.thesis_id)
        for hypothesis in hypotheses:
            hypothesis_node_id = _node_id(GraphNodeKind.HYPOTHESIS, hypothesis.hypothesis_id)
            self.graph.add_node(
                GraphNode(
                    hypothesis_node_id,
                    GraphNodeKind.HYPOTHESIS,
                    hypothesis.name or hypothesis.statement,
                    content=hypothesis.statement,
                    security_id=thesis.security_id,
                    metadata={
                        "importance": hypothesis.importance.value,
                        "status": hypothesis.status,
                        "invalidation_rule": hypothesis.invalidation_rule,
                    },
                )
            )
            self.graph.add_edge(
                GraphEdge(thesis_node_id, hypothesis_node_id, GraphEdgeKind.HAS_HYPOTHESIS)
            )
            variable_label = hypothesis.name or hypothesis.hypothesis_type
            variable_node_id = _variable_id(thesis.security_id, variable_label)
            self.graph.add_node(
                GraphNode(
                    variable_node_id,
                    GraphNodeKind.BUSINESS_VARIABLE,
                    variable_label,
                    content=hypothesis.hypothesis_type,
                    security_id=thesis.security_id,
                )
            )
            self.graph.add_edge(
                GraphEdge(hypothesis_node_id, variable_node_id, GraphEdgeKind.DEPENDS_ON)
            )
            for mapping in self.uow.thesis.list_mappings(hypothesis.hypothesis_id):
                if (
                    not self.include_pending
                    and mapping.confirmation_status is not ConfirmationStatus.CONFIRMED
                ):
                    continue
                metric = self.uow.metrics.get(mapping.metric_id, mapping.metric_version)
                metric_node_id = _node_id(
                    GraphNodeKind.METRIC, f"{mapping.metric_id}:{mapping.metric_version}"
                )
                self.graph.add_node(
                    GraphNode(
                        metric_node_id,
                        GraphNodeKind.METRIC,
                        metric.name if metric else mapping.metric_id,
                        content=(metric.definition or "") if metric else "",
                        metadata={
                            "metric_id": mapping.metric_id,
                            "metric_version": mapping.metric_version,
                            "unit": metric.unit if metric else None,
                        },
                    )
                )
                self.graph.add_edge(
                    GraphEdge(
                        hypothesis_node_id,
                        metric_node_id,
                        GraphEdgeKind.MEASURED_BY,
                        confirmed=(mapping.confirmation_status is ConfirmationStatus.CONFIRMED),
                    )
                )
                self.graph.add_edge(
                    GraphEdge(variable_node_id, metric_node_id, GraphEdgeKind.MEASURED_BY)
                )
                self._metric_nodes[(mapping.metric_id, mapping.metric_version)] = metric_node_id
                self._metric_variables.setdefault(metric_node_id, set()).add(variable_node_id)
                for observation in self.uow.observations.list_for_metric(
                    thesis.security_id, mapping.metric_id
                ):
                    if observation.metric_version != mapping.metric_version:
                        continue
                    observation_time = datetime.combine(
                        observation.observation_date, datetime.min.time(), tzinfo=UTC
                    )
                    if self.as_of and observation_time > self.as_of:
                        continue
                    observation_node_id = _node_id(
                        GraphNodeKind.OBSERVATION,
                        f"{thesis.security_id}:{mapping.metric_id}:{observation.period}:{observation.data_version}",
                    )
                    value = (
                        str(observation.actual_value)
                        if observation.actual_value is not None
                        else observation.raw_value
                        if hasattr(observation, "raw_value")
                        else ""
                    )
                    self.graph.add_node(
                        GraphNode(
                            observation_node_id,
                            GraphNodeKind.OBSERVATION,
                            f"{observation.period} {value} {observation.unit}".strip(),
                            security_id=thesis.security_id,
                            published_at=observation_time,
                            metadata={"data_version": observation.data_version},
                        )
                    )
                    self.graph.add_edge(
                        GraphEdge(
                            metric_node_id,
                            observation_node_id,
                            GraphEdgeKind.HAS_OBSERVATION,
                        )
                    )
                    if observation.source_document_id:
                        document_node_id = self.source_layer.add_document(
                            observation.source_document_id, fallback_security=thesis.security_id
                        )
                        if document_node_id:
                            self.graph.add_edge(
                                GraphEdge(
                                    observation_node_id,
                                    document_node_id,
                                    GraphEdgeKind.DERIVED_FROM,
                                )
                            )
        # 先完成假设—变量—指标映射，再加载正文事实，才能建立事实到指标的边。
        if thesis.source_document_id:
            self.source_layer.add_document(
                thesis.source_document_id, fallback_security=thesis.security_id
            )
        self.observation_layer.add_evidence_chain(thesis.thesis_id, thesis.security_id)
        return True

    def _project_evidence(self, thesis_id: str, security_id: str) -> None:
        all_relations = self.uow.relations.list_for_thesis(thesis_id)
        relations = [
            relation
            for relation in all_relations
            if relation.status is not ConfirmationStatus.DEACTIVATED
            and relation.status is not ConfirmationStatus.REJECTED
            and (self.include_pending or relation.status is ConfirmationStatus.CONFIRMED)
        ]
        evidence_relations: list[tuple[EvidenceRecord, str, ImpactDirection, bool]] = []
        if all_relations:
            for relation in relations:
                evidence = self.uow.evidence.get(relation.evidence_id)
                if evidence is not None:
                    evidence_relations.append(
                        (
                            evidence,
                            relation.hypothesis_id,
                            relation.direction,
                            relation.status is ConfirmationStatus.CONFIRMED,
                        )
                    )
        else:
            for evidence in self.uow.evidence.list_for_thesis(thesis_id):
                if evidence.confirmation_status in {
                    ConfirmationStatus.REJECTED,
                    ConfirmationStatus.DEACTIVATED,
                }:
                    continue
                if (
                    not self.include_pending
                    and evidence.confirmation_status is not ConfirmationStatus.CONFIRMED
                ):
                    continue
                evidence_relations.append(
                    (
                        evidence,
                        evidence.hypothesis_id,
                        evidence.direction,
                        evidence.confirmation_status is ConfirmationStatus.CONFIRMED,
                    )
                )

        for evidence, hypothesis_id, direction, confirmed in evidence_relations:
            if self.as_of and evidence.disclosed_at and evidence.disclosed_at > self.as_of:
                continue
            hypothesis_node_id = _node_id(GraphNodeKind.HYPOTHESIS, hypothesis_id)
            if hypothesis_node_id not in self.graph.nodes:
                continue
            evidence_node_id = _node_id(GraphNodeKind.EVIDENCE, evidence.evidence_id)
            self.graph.add_node(
                GraphNode(
                    evidence_node_id,
                    GraphNodeKind.EVIDENCE,
                    evidence.fact_excerpt or evidence.evidence_id,
                    content=evidence.fact_excerpt or "",
                    security_id=security_id,
                    published_at=evidence.disclosed_at,
                    visibility_label=evidence.source_visibility_label,
                    locator=evidence.evidence_locator,
                    metadata={
                        "direction": direction.value,
                        "confirmation_status": evidence.confirmation_status.value,
                    },
                )
            )
            self.graph.add_edge(
                GraphEdge(
                    hypothesis_node_id,
                    evidence_node_id,
                    _direction_edge(direction),
                    confirmed=confirmed,
                    provenance_locator=evidence.evidence_locator,
                )
            )
            if evidence.event_id:
                event = self.uow.events.get(evidence.event_id)
                if event is not None:
                    if self.as_of and event.disclosure_time > self.as_of:
                        continue
                    event_node_id = _node_id(GraphNodeKind.EVENT, event.event_id)
                    self.graph.add_node(
                        GraphNode(
                            event_node_id,
                            GraphNodeKind.EVENT,
                            event.summary,
                            content=event.event_type,
                            security_id=event.security_id or security_id,
                            published_at=event.disclosure_time,
                            metadata={"event_version": event.version},
                        )
                    )
                    self.graph.add_edge(
                        GraphEdge(evidence_node_id, event_node_id, GraphEdgeKind.DERIVED_FROM)
                    )
                    if event.document_id:
                        document_node_id = self.source_layer.add_document(
                            event.document_id, fallback_security=event.security_id or security_id
                        )
                        if document_node_id:
                            self.graph.add_edge(
                                GraphEdge(
                                    event_node_id,
                                    document_node_id,
                                    GraphEdgeKind.DISCLOSED_IN,
                                )
                            )
            source_document_id = evidence.source_document_id
            if source_document_id:
                self.source_layer.add_document(source_document_id, fallback_security=security_id)
            if evidence.evidence_locator:
                segment_node_id = _node_id(GraphNodeKind.SEGMENT, evidence.evidence_locator)
                if segment_node_id not in self.graph.nodes and evidence.fact_excerpt:
                    published_at = evidence.disclosed_at or _EPOCH
                    self.documents[evidence.evidence_locator] = RetrievalDocument(
                        document_id=source_document_id or evidence.evidence_id,
                        security_id=security_id,
                        locator=evidence.evidence_locator,
                        content=evidence.fact_excerpt,
                        published_at=published_at,
                        visibility_label=evidence.source_visibility_label,
                        source=evidence.source_document_title or source_document_id or "evidence",
                        metadata={"evidence_id": evidence.evidence_id},
                    )
                    self.graph.add_node(
                        GraphNode(
                            segment_node_id,
                            GraphNodeKind.SEGMENT,
                            evidence.evidence_locator,
                            content=evidence.fact_excerpt,
                            security_id=security_id,
                            published_at=published_at,
                            visibility_label=evidence.source_visibility_label,
                            locator=evidence.evidence_locator,
                        )
                    )
                if segment_node_id in self.graph.nodes:
                    self.graph.add_edge(
                        GraphEdge(
                            evidence_node_id,
                            segment_node_id,
                            GraphEdgeKind.CITES,
                            confirmed=confirmed,
                            provenance_locator=evidence.evidence_locator,
                        )
                    )

    def _project_document(self, document_id: str, *, fallback_security: str) -> str | None:
        document_node_id = _node_id(GraphNodeKind.DOCUMENT, document_id)
        if document_id in self._loaded_documents:
            return document_node_id if document_node_id in self.graph.nodes else None
        self._loaded_documents.add(document_id)
        document = self.uow.documents.get(document_id)
        if document is None or document.deleted_at is not None:
            return None
        if self.as_of and document.published_at > self.as_of:
            return None
        security_id = document.security_id or fallback_security
        self.graph.add_node(
            GraphNode(
                document_node_id,
                GraphNodeKind.DOCUMENT,
                document.title or document.document_id,
                content=document.doc_type or "",
                security_id=security_id,
                published_at=document.published_at,
                visibility_label=document.visibility_label,
                metadata={"document_id": document.document_id, "source_id": document.source_id},
            )
        )
        segments = self.uow.documents.list_segments(document_id)
        for segment in segments:
            segment_node_id = _node_id(GraphNodeKind.SEGMENT, segment.locator)
            self.graph.add_node(
                GraphNode(
                    segment_node_id,
                    GraphNodeKind.SEGMENT,
                    segment.locator,
                    content=segment.content,
                    security_id=security_id,
                    published_at=document.published_at,
                    visibility_label=document.visibility_label,
                    locator=segment.locator,
                    metadata={"document_id": document_id, "page": segment.page},
                )
            )
            self.graph.add_edge(
                GraphEdge(document_node_id, segment_node_id, GraphEdgeKind.CONTAINS)
            )
            self.documents[segment.locator] = RetrievalDocument(
                document_id=document_id,
                security_id=security_id,
                locator=segment.locator,
                content=segment.content,
                published_at=document.published_at,
                visibility_label=document.visibility_label,
                source=document.title or document_id,
                metadata={"page": segment.page, "document_type": document.doc_type},
            )
        for fact in self.uow.documents.list_facts(document_id):
            fact_node_id = _node_id(GraphNodeKind.FACT, fact.fact_id)
            self.graph.add_node(
                GraphNode(
                    fact_node_id,
                    GraphNodeKind.FACT,
                    fact.metric_name,
                    content=fact.raw_text,
                    security_id=security_id,
                    published_at=document.published_at,
                    visibility_label=document.visibility_label,
                    locator=fact.locator,
                    metadata={
                        "fact_type": fact.fact_type,
                        "direction": fact.direction,
                        "extraction_version": fact.extraction_version,
                    },
                )
            )
            segment_node_id = _node_id(GraphNodeKind.SEGMENT, fact.locator)
            if segment_node_id not in self.graph.nodes:
                self.graph.add_node(
                    GraphNode(
                        segment_node_id,
                        GraphNodeKind.SEGMENT,
                        fact.locator,
                        content=fact.raw_text,
                        security_id=security_id,
                        published_at=document.published_at,
                        visibility_label=document.visibility_label,
                        locator=fact.locator,
                    )
                )
                self.graph.add_edge(
                    GraphEdge(document_node_id, segment_node_id, GraphEdgeKind.CONTAINS)
                )
                self.documents[fact.locator] = RetrievalDocument(
                    document_id=document_id,
                    security_id=security_id,
                    locator=fact.locator,
                    content=fact.raw_text,
                    published_at=document.published_at,
                    visibility_label=document.visibility_label,
                    source=document.title or document_id,
                )
            self.graph.add_edge(
                GraphEdge(
                    segment_node_id,
                    fact_node_id,
                    GraphEdgeKind.STATES_FACT,
                    provenance_locator=fact.locator,
                )
            )
            for metric_node_id in self.semantic_layer.matching_metric_nodes(fact.metric_name):
                self.graph.add_edge(
                    GraphEdge(
                        fact_node_id,
                        metric_node_id,
                        GraphEdgeKind.OBSERVES,
                        provenance_locator=fact.locator,
                    )
                )
                for variable_node_id in self._metric_variables.get(metric_node_id, ()):
                    self.graph.add_edge(
                        GraphEdge(
                            fact_node_id,
                            variable_node_id,
                            GraphEdgeKind.AFFECTS,
                            provenance_locator=fact.locator,
                        )
                    )
        return document_node_id

    def _matching_metric_nodes(self, fact_metric: str) -> list[str]:
        matches: list[str] = []
        for metric_node_id in self._metric_variables:
            node = self.graph.nodes[metric_node_id]
            if self.metric_vocabulary.matches(fact_metric, node.label):
                matches.append(metric_node_id)
        return matches


def _layer_hash(graph: InvestmentKnowledgeGraph, layer: GraphLayer) -> str:
    node_ids = {node.node_id for node in graph.nodes.values() if node.layer is layer}
    payload = {
        "nodes": [
            {
                "id": node.node_id,
                "kind": node.kind.value,
                "label": node.label,
                "content": node.content,
                "security_id": node.security_id,
                "published_at": node.published_at,
                "visibility": node.visibility_label,
                "locator": node.locator,
                "metadata": node.metadata,
            }
            for node in sorted(graph.nodes.values(), key=lambda item: item.node_id)
            if node.node_id in node_ids
        ],
        "outgoing_edges": [
            {
                "source": edge.source_id,
                "target": edge.target_id,
                "kind": edge.kind.value,
                "weight": edge.weight,
                "confirmed": edge.confirmed,
                "provenance": edge.provenance_locator,
                "metadata": edge.metadata,
            }
            for edge in sorted(
                graph.edges,
                key=lambda item: (item.source_id, item.target_id, item.kind.value),
            )
            if edge.source_id in node_ids
        ],
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return sha256(serialized.encode("utf-8")).hexdigest()


def _build_snapshot(
    graph: InvestmentKnowledgeGraph,
    *,
    thesis_ids: tuple[str, ...],
    include_pending: bool,
    as_of: datetime | None,
    vocabulary_version: str,
) -> GraphSnapshot:
    layer_counts = graph.layer_counts()
    layers = tuple(
        GraphLayerSnapshot(
            layer=layer,
            node_count=layer_counts[layer],
            content_hash=_layer_hash(graph, layer),
        )
        for layer in GraphLayer
    )
    security_ids = tuple(
        sorted({node.security_id for node in graph.nodes.values() if node.security_id is not None})
    )
    identity = json.dumps(
        {
            "schema_version": GRAPH_SCHEMA_VERSION,
            "builder_version": GRAPH_BUILDER_VERSION,
            "vocabulary_version": vocabulary_version,
            "as_of": as_of,
            "include_pending": include_pending,
            "thesis_ids": thesis_ids,
            "security_ids": security_ids,
            "layers": [(item.layer.value, item.node_count, item.content_hash) for item in layers],
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    snapshot_id = f"graph-snapshot:{sha256(identity.encode('utf-8')).hexdigest()[:24]}"
    return GraphSnapshot(
        snapshot_id=snapshot_id,
        schema_version=GRAPH_SCHEMA_VERSION,
        builder_version=GRAPH_BUILDER_VERSION,
        vocabulary_version=vocabulary_version,
        built_at=datetime.now(UTC),
        as_of=as_of,
        include_pending=include_pending,
        thesis_ids=thesis_ids,
        security_ids=security_ids,
        layers=layers,
    )


def graph_snapshot_metadata(snapshot: GraphSnapshot) -> dict[str, object]:
    """生成可安全持久化和返回前端的图快照清单，不包含节点正文。"""

    return {
        "snapshot_id": snapshot.snapshot_id,
        "schema_version": snapshot.schema_version,
        "builder_version": snapshot.builder_version,
        "vocabulary_version": snapshot.vocabulary_version,
        "built_at": snapshot.built_at.isoformat(),
        "as_of": snapshot.as_of.isoformat() if snapshot.as_of else None,
        "thesis_ids": list(snapshot.thesis_ids),
        "security_ids": list(snapshot.security_ids),
        "layers": [
            {
                "layer": item.layer.value,
                "node_count": item.node_count,
                "content_hash": item.content_hash,
            }
            for item in snapshot.layers
        ],
    }


def build_graph_rag_corpus(
    uow: UnitOfWork,
    *,
    thesis_ids: list[str] | tuple[str, ...],
    include_pending: bool = False,
    as_of: datetime | None = None,
    metric_vocabulary: MetricVocabulary = DEFAULT_METRIC_VOCABULARY,
) -> GraphRagCorpus:
    """构建指定逻辑的只读图；默认只纳入已确认关系和指标映射。"""

    builder = _CorpusBuilder(
        uow,
        include_pending=include_pending,
        as_of=as_of,
        metric_vocabulary=metric_vocabulary,
    )
    included = [thesis_id for thesis_id in thesis_ids if builder.add_thesis(thesis_id)]
    included_ids = tuple(included)
    return GraphRagCorpus(
        graph=builder.graph,
        documents=tuple(builder.documents.values()),
        thesis_ids=included_ids,
        snapshot=_build_snapshot(
            builder.graph,
            thesis_ids=included_ids,
            include_pending=include_pending,
            as_of=as_of,
            vocabulary_version=metric_vocabulary.version,
        ),
    )


def build_graph_retriever(
    uow: UnitOfWork,
    *,
    thesis_ids: list[str] | tuple[str, ...],
    text_retriever: Retriever,
    include_pending: bool = False,
    text_weight: float = 0.35,
    graph_weight: float = 0.65,
    max_hops: int = 5,
    assist_only: bool = False,
    as_of: datetime | None = None,
    metric_vocabulary: MetricVocabulary = DEFAULT_METRIC_VOCABULARY,
) -> Retriever:
    corpus = build_graph_rag_corpus(
        uow,
        thesis_ids=thesis_ids,
        include_pending=include_pending,
        as_of=as_of,
        metric_vocabulary=metric_vocabulary,
    )
    return build_graph_retriever_from_corpus(
        corpus,
        text_retriever=text_retriever,
        include_pending=include_pending,
        text_weight=text_weight,
        graph_weight=graph_weight,
        max_hops=max_hops,
        assist_only=assist_only,
    )


def build_graph_retriever_from_corpus(
    corpus: GraphRagCorpus,
    *,
    text_retriever: Retriever,
    include_pending: bool = False,
    text_weight: float = 0.35,
    graph_weight: float = 0.65,
    max_hops: int = 5,
    assist_only: bool = False,
) -> Retriever:
    """复用已构建语料并保证包装幂等，避免长生命周期 Runtime 套娃。"""

    while isinstance(
        text_retriever,
        GraphRetriever | RankStableGraphAssistRetriever | EvidenceFusionGraphRetriever,
    ):
        text_retriever = text_retriever.text_retriever
    graph_retriever = GraphRetriever(
        text_retriever=text_retriever,
        graph=corpus.graph,
        text_weight=text_weight,
        graph_weight=graph_weight,
        max_hops=max_hops,
        include_unconfirmed_edges=include_pending,
        snapshot_metadata=graph_snapshot_metadata(corpus.snapshot),
    )
    documents = list(corpus.documents)
    if not assist_only:
        fusion = EvidenceFusionGraphRetriever(
            text_retriever=text_retriever,
            bm25_retriever=BM25Retriever(),
            graph_retriever=graph_retriever,
        )
        fusion.add(documents)
        return fusion
    graph_retriever.add(documents)
    return RankStableGraphAssistRetriever(
        text_retriever=text_retriever,
        graph_retriever=graph_retriever,
    )


def graph_candidate_context(corpus: GraphRagCorpus, thesis_id: str) -> str:
    """返回逻辑的研究/语义层确定性文本画像，供候选排序而非正式证据使用。"""

    start = _node_id(GraphNodeKind.THESIS, thesis_id)
    if start not in corpus.graph.nodes:
        return ""
    visited = {start}
    frontier = [(start, 0)]
    values: list[str] = []
    while frontier:
        node_id, hops = frontier.pop(0)
        node = corpus.graph.nodes[node_id]
        if node.layer in {GraphLayer.RESEARCH, GraphLayer.SEMANTIC}:
            values.extend((node.label, node.content))
        if hops >= 3:
            continue
        for neighbor_id, _, _ in corpus.graph.neighbors(node_id):
            if neighbor_id in visited:
                continue
            neighbor = corpus.graph.nodes[neighbor_id]
            if neighbor.layer not in {GraphLayer.RESEARCH, GraphLayer.SEMANTIC}:
                continue
            visited.add(neighbor_id)
            frontier.append((neighbor_id, hops + 1))
    return " ".join(value for value in values if value)
