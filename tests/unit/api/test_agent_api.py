from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.ai.gateway import Gateway
from app.ai.observability import NullRuntimeRecorder
from app.ai.runtime import InvestmentResearchAgent
from app.api.deps import get_settings, get_uow
from app.api.main import create_app
from app.api.routers import thesis as thesis_router
from app.core.config import Settings
from app.core.domain import AssetSearchHitRecord, SecurityRecord
from app.services import agent_workflow
from tests.fakes import build_fake_uow


def _settings() -> Settings:
    return Settings(_env_file=None, llm_provider="local", debug=True)


def _rag_hits(*args, **kwargs) -> list[AssetSearchHitRecord]:
    return [
        AssetSearchHitRecord(
            document_id="DOC-BASE",
            locator="DOC-BASE#paragraph-1",
            content="新能源汽车月度销量持续增长，终端需求保持旺盛。",
            visibility_label="内部",
            rank=1.0,
            published_at=datetime(2026, 1, 1, tzinfo=UTC),
            source="test",
        )
    ]


def test_create_draft_automatically_attaches_controlled_metric_candidates(monkeypatch) -> None:
    settings = _settings()
    uow = build_fake_uow()
    uow.securities.add(SecurityRecord("002594", "比亚迪", industry="新能源汽车"))
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_uow] = lambda: uow
    monkeypatch.setattr(thesis_router, "SqlRuntimeRecorder", NullRuntimeRecorder)
    monkeypatch.setattr(thesis_router.asset_service, "hybrid_retrieve", _rag_hits)

    try:
        with TestClient(application) as client:
            response = client.post(
                "/api/theses/drafts",
                headers={"X-User-Id": "analyst-mvp"},
                json={
                    "security_id": "002594",
                    "view": "新能源汽车月度销量持续增长能够验证终端需求",
                    "use_rag": True,
                },
            )
    finally:
        application.dependency_overrides.clear()

    assert response.status_code == 201
    hypotheses = response.json()["hypotheses"]
    assert len(hypotheses) >= 2
    assert hypotheses[0]["metric_suggestions"]
    first = hypotheses[0]["metric_suggestions"][0]
    assert first["metric_id"]
    assert first["threshold_suggestion"]["requires_human_review"] is True
    assert uow.thesis.list_mappings(hypotheses[0]["hypothesis_id"]) == []


def test_metric_recommendation_endpoint_returns_agent_envelope(monkeypatch) -> None:
    settings = _settings()
    uow = build_fake_uow()
    uow.securities.add(SecurityRecord("002594", "比亚迪", industry="新能源汽车"))
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_uow] = lambda: uow
    monkeypatch.setattr(thesis_router, "SqlRuntimeRecorder", NullRuntimeRecorder)
    monkeypatch.setattr(thesis_router.asset_service, "hybrid_retrieve", _rag_hits)
    monkeypatch.setattr(
        agent_workflow,
        "build_runtime",
        lambda _: InvestmentResearchAgent.build(Gateway.build(settings)),
    )

    try:
        with TestClient(application) as client:
            created = client.post(
                "/api/theses/drafts",
                headers={"X-User-Id": "analyst-mvp"},
                json={
                    "security_id": "002594",
                    "view": "新能源汽车月度销量持续增长能够验证终端需求",
                    "use_rag": True,
                },
            ).json()
            hypothesis_id = created["hypotheses"][0]["hypothesis_id"]
            response = client.post(
                f"/api/agent/theses/{created['thesis_id']}/hypotheses/"
                f"{hypothesis_id}/metric-recommendations",
                headers={"X-User-Id": "analyst-mvp"},
                json={"top_k": 3, "as_of": "2026-08-27"},
            )
    finally:
        application.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["task"] == "metric_recommend"
    assert body["requires_human_review"] is True
    assert 1 <= len(body["payload"]["recommendations"]) <= 3
