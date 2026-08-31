from __future__ import annotations

from datetime import UTC, date, datetime

from app.ai.graph_rag import GraphLayer, GraphNodeKind
from app.ai.retrieval import KeywordRetriever, RetrievalQuery
from app.core.domain import (
    DocumentFactRecord,
    DocumentRecord,
    DocumentSegmentRecord,
    EvidenceRecord,
    EvidenceRelationRecord,
    HypothesisRecord,
    MetricMappingRecord,
    SecurityRecord,
    ThesisRecord,
)
from app.core.enums import (
    ConfirmationStatus,
    ExpectationDirection,
    ImpactDirection,
    Importance,
    ThesisStatus,
)
from app.services.graph_rag import (
    build_graph_rag_corpus,
    build_graph_retriever,
    graph_snapshot_metadata,
    verify_graph_snapshot_metadata,
)
from tests.fakes import build_fake_uow


def _dt(day: int) -> datetime:
    return datetime(2026, 8, day, tzinfo=UTC)


def _uow_with_confirmed_graph():
    uow = build_fake_uow()
    uow.securities.add(SecurityRecord("688981", "中芯国际"))
    uow.thesis.add(
        ThesisRecord(
            thesis_id="THS-1",
            security_id="688981",
            title="产能利用率驱动收入增长",
            direction="看多",
            core_view="需求与出货保持增长",
            established_on=date(2026, 1, 1),
            owner="researcher",
            status=ThesisStatus.VALIDATING,
        )
    )
    uow.thesis.add_hypothesis(
        HypothesisRecord(
            hypothesis_id="H1",
            thesis_id="THS-1",
            statement="营业收入保持增长",
            hypothesis_type="经营",
            importance=Importance.CORE,
            name="需求与出货",
        )
    )
    uow.thesis.add_mapping(
        MetricMappingRecord(
            mapping_id="MAP-1",
            hypothesis_id="H1",
            metric_id="MET-DEMO-001",
            expected_direction=ExpectationDirection.HIGHER_BETTER,
            confirmation_status=ConfirmationStatus.CONFIRMED,
        )
    )
    uow.documents.add(
        DocumentRecord(
            document_id="DOC-1",
            published_at=_dt(2),
            content_hash="hash",
            parser_version="v1",
            title="季度报告",
            security_id="688981",
            visibility_label="公开",
        ),
        [DocumentSegmentRecord("DOC-1", "DOC-1#paragraph-2", 1, "营业收入同比增长16%。")],
        [
            DocumentFactRecord(
                fact_id="FACT-1",
                document_id="DOC-1",
                locator="DOC-1#paragraph-2",
                fact_type="同比",
                metric_name="营收同比",
                direction="上升",
                raw_text="营业收入同比增长16%。",
                extraction_version="fact-v1",
            )
        ],
    )
    evidence = EvidenceRecord(
        evidence_id="EVD-1",
        thesis_id="THS-1",
        hypothesis_id="H1",
        evidence_type="事实",
        direction=ImpactDirection.SUPPORT,
        evidence_locator="DOC-1#paragraph-2",
        confirmation_status=ConfirmationStatus.CONFIRMED,
        source_visibility_label="公开",
        security_id="688981",
        fact_excerpt="营业收入同比增长16%。",
        source_document_id="DOC-1",
        source_document_title="季度报告",
        disclosed_at=_dt(2),
    )
    uow.evidence.add(evidence)
    uow.relations.add(
        EvidenceRelationRecord(
            relation_id="REL-1",
            evidence_id="EVD-1",
            thesis_id="THS-1",
            hypothesis_id="H1",
            direction=ImpactDirection.SUPPORT,
            strength="高",
            status=ConfirmationStatus.CONFIRMED,
            created_by="researcher",
        )
    )
    return uow


def test_service_从正式领域对象构建事件事实指标假设图() -> None:
    corpus = build_graph_rag_corpus(_uow_with_confirmed_graph(), thesis_ids=["THS-1"])

    kinds = {node.kind for node in corpus.graph.nodes.values()}
    assert {
        GraphNodeKind.SECURITY,
        GraphNodeKind.THESIS,
        GraphNodeKind.HYPOTHESIS,
        GraphNodeKind.BUSINESS_VARIABLE,
        GraphNodeKind.METRIC,
        GraphNodeKind.FACT,
        GraphNodeKind.EVIDENCE,
        GraphNodeKind.SEGMENT,
    } <= kinds
    assert corpus.graph.edge_count >= 8
    assert [document.locator for document in corpus.documents] == ["DOC-1#paragraph-2"]


def test_service_构建的_retriever_可从假设走到事实原文() -> None:
    retriever = build_graph_retriever(
        _uow_with_confirmed_graph(),
        thesis_ids=["THS-1"],
        text_retriever=KeywordRetriever(),
    )

    result = retriever.search(
        RetrievalQuery(
            text="需求与出货",
            security_id="688981",
            seed_node_ids=frozenset({"hypothesis:H1"}),
            top_k=2,
        )
    )

    assert result.items[0].locator == "DOC-1#paragraph-2"
    assert result.items[0].metadata["graph_paths"]
    assert result.items[0].metadata["graph_snapshot"]["snapshot_id"].startswith("graph-snapshot:")


def test_service_默认排除待确认关系() -> None:
    uow = _uow_with_confirmed_graph()
    relation = uow.relations.get("REL-1")
    assert relation is not None
    relation.status = ConfirmationStatus.PENDING
    uow.relations.update(relation)

    corpus = build_graph_rag_corpus(uow, thesis_ids=["THS-1"])

    assert "evidence:EVD-1" not in corpus.graph.nodes


def test_service_生成稳定快照并记录各知识层清单() -> None:
    uow = _uow_with_confirmed_graph()

    first = build_graph_rag_corpus(uow, thesis_ids=["THS-1"])
    second = build_graph_rag_corpus(uow, thesis_ids=["THS-1"])

    assert first.snapshot.snapshot_id == second.snapshot.snapshot_id
    assert first.snapshot.schema_version == "investment-knowledge-layers-v2"
    assert first.snapshot.vocabulary_version == "metric-aliases-v1"
    counts = {item.layer: item.node_count for item in first.snapshot.layers}
    assert counts[GraphLayer.SOURCE] >= 2
    assert counts[GraphLayer.OBSERVATION] >= 1
    assert counts[GraphLayer.SEMANTIC] >= 2
    assert counts[GraphLayer.RESEARCH] >= 4

    metadata = graph_snapshot_metadata(first.snapshot)
    assert verify_graph_snapshot_metadata(metadata) is True
    metadata["layers"][0]["content_hash"] = "0" * 64
    assert verify_graph_snapshot_metadata(metadata) is False


def test_service_as_of_在构建阶段排除未来来源() -> None:
    corpus = build_graph_rag_corpus(
        _uow_with_confirmed_graph(),
        thesis_ids=["THS-1"],
        as_of=_dt(1),
    )

    assert corpus.documents == ()
    assert "document:DOC-1" not in corpus.graph.nodes
    assert corpus.snapshot.as_of == _dt(1)
