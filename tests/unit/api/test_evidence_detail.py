"""证据详情与关联目标搜索的路由回归测试。"""

from datetime import UTC, date, datetime

from fastapi.testclient import TestClient

from app.api.deps import get_actor, get_uow
from app.api.main import app
from app.core.domain import EvidenceRecord, HypothesisRecord, ThesisRecord
from app.core.enums import ConfirmationStatus, ImpactDirection, Importance, ThesisStatus
from app.services.permission import Actor
from tests.fakes import build_fake_uow


def test_detail_hides_legacy_relation_and_search_filters_to_owner() -> None:
    """详情只返回证据本体；关联目标搜索不能暴露团队内其他人的逻辑。"""
    uow = build_fake_uow()
    uow.thesis.add(
        ThesisRecord(
            thesis_id="THS-SG-001",
            security_id="300274",
            title="阳光电源真实案例",
            direction="看多",
            core_view="公开数据验证用逻辑",
            established_on=date(2025, 1, 10),
            owner="示例研究员",
            status=ThesisStatus.VALIDATING,
            visibility="团队",
            team="权益研究",
        )
    )
    uow.thesis.add_hypothesis(
        HypothesisRecord(
            hypothesis_id="HYP-SG-001",
            thesis_id="THS-SG-001",
            statement="海外储能需求保持增长",
            hypothesis_type="行业",
            importance=Importance.CORE,
        )
    )
    uow.evidence.add(
        EvidenceRecord(
            evidence_id="EVD-SG-001",
            thesis_id="THS-SG-001",
            hypothesis_id="HYP-SG-001",
            evidence_type="事实",
            direction=ImpactDirection.SUPPORT,
            evidence_locator="DOC-SG-001#paragraph-1",
            confirmation_status=ConfirmationStatus.PENDING,
            security_id="300274",
            fact_excerpt="公开披露的储能业务数据。",
            source_document_id="DOC-SG-001",
            source_document_title="阳光电源公开披露资料",
            disclosed_at=datetime(2026, 8, 1, tzinfo=UTC),
            ingested_at=datetime(2026, 8, 2, tzinfo=UTC),
            source_url="https://www.cninfo.com.cn/",
            source_visibility_label="公开",
            retrieval_trace={
                "available": True,
                "retrieval_mode": "graph",
                "retrieval_version": "investment-graph-rag-v2-layered[keyword-v1]",
                "locator": "DOC-SG-001#paragraph-1",
                "final_score": 0.74,
                "score_components": {"text": 0.62, "graph": 0.81},
                "graph_paths": [
                    {
                        "score": 0.81,
                        "node_ids": ["hypothesis:HYP-SG-001", "segment:DOC-SG-001#paragraph-1"],
                        "node_kinds": ["投资假设", "原文片段"],
                        "layers": ["投资研究层", "原始证据层"],
                        "relations": ["引用原文"],
                        "provenance_locators": ["DOC-SG-001#paragraph-1"],
                        "explanation": "海外储能需求保持增长 --引用原文--> 原文第1段",
                    }
                ],
                "graph_snapshot": {
                    "snapshot_id": "graph-snapshot:test",
                    "schema_version": "investment-knowledge-layers-v2",
                    "builder_version": "layered-corpus-builder-v1",
                    "vocabulary_version": "metric-aliases-v1",
                    "built_at": "2026-08-24T00:00:00+00:00",
                    "as_of": "2026-08-01T00:00:00+00:00",
                    "thesis_ids": ["THS-SG-001"],
                    "security_ids": ["300274"],
                    "layers": [
                        {
                            "layer": "投资研究层",
                            "node_count": 3,
                            "content_hash": "abc123",
                        }
                    ],
                },
            },
        )
    )
    app.dependency_overrides[get_uow] = lambda: uow
    app.dependency_overrides[get_actor] = lambda: Actor(
        user_id="示例研究员", teams=frozenset({"权益研究"})
    )
    try:
        client = TestClient(app)
        detail = client.get("/api/evidence/EVD-SG-001")
        assert detail.status_code == 200
        assert detail.json()["security_id"] == "300274"
        assert "thesis_id" not in detail.json()
        trace = client.get("/api/evidence/EVD-SG-001/retrieval-trace")
        assert trace.status_code == 200
        assert trace.json()["score_components"] == {"text": 0.62, "graph": 0.81}
        assert trace.json()["graph_paths"][0]["layers"] == ["投资研究层", "原始证据层"]
        assert trace.json()["graph_snapshot"]["snapshot_id"] == "graph-snapshot:test"
        assert (
            client.get("/api/theses?security_id=300274&page=1&page_size=20").json()["page"]["total"]
            == 1
        )
        app.dependency_overrides[get_actor] = lambda: Actor(user_id="无权限用户")
        assert client.get("/api/evidence/EVD-SG-001/retrieval-trace").status_code == 404
    finally:
        app.dependency_overrides.clear()
