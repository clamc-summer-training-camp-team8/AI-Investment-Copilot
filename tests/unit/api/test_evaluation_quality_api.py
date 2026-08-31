"""独立金标质量中心 API 契约。"""

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.deps import get_settings
from app.api.main import create_app
from app.core.config import Settings

HEADERS = {"X-User-Id": "quality-reviewer"}


def test_质量中心返回冻结金标与门禁() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/evaluation/gold-quality", headers=HEADERS)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["gold_version"] == "final-gold-v3-20260826"
    assert payload["summary"]["total_samples"] == 360
    assert payload["summary"]["consensus_samples"] == 199
    assert payload["summary"]["adjudicated_samples"] == 161
    assert payload["summary"]["gold_samples"] == 360
    assert payload["summary"]["evaluation_eligible_samples"] == 358
    assert payload["summary"]["production_gold_ready"] is True
    assert payload["summary"]["graph_rag_rollout_ready"] is True
    graph_benchmark = payload["system_benchmarks"]["graph_rag"]
    assert graph_benchmark["authoritative_blind"] is True
    assert graph_benchmark["evaluated_queries"] == 30
    assert graph_benchmark["graph_rag"]["recall_at_k"]["5"] == 0.8247
    assert graph_benchmark["graph_rag"]["mrr"] == 0.8983
    assert graph_benchmark["safety"]["permission_leakage_count"] == 0
    assert graph_benchmark["rollout_ready"] is True
    assert {item["task"] for item in payload["tasks"]} == {
        "event",
        "body_fact",
        "graph_relevance",
    }


def test_质量报告缺失时明确返回503(tmp_path: Path) -> None:
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: Settings(
        gold_quality_report_path=tmp_path / "missing.json"
    )
    with TestClient(application) as client:
        response = client.get("/api/evaluation/gold-quality", headers=HEADERS)

    assert response.status_code == 503


def test_质量中心禁止匿名调用() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/evaluation/gold-quality")

    assert response.status_code == 401
