from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.api.deps import get_uow
from app.api.main import create_app
from app.core.domain import HypothesisRecord, SecurityRecord, ThesisRecord
from app.core.enums import Importance, ThesisStatus, Visibility
from tests.fakes import build_fake_uow


def _draft_uow():
    uow = build_fake_uow()
    uow.thesis.add(
        ThesisRecord(
            thesis_id="THS-CONFIG-1",
            security_id="DEMO001",
            title="网页发布闭环",
            direction="观察",
            core_view="验证网页可以配置并发布",
            established_on=date(2026, 8, 12),
            owner="analyst-mvp",
            status=ThesisStatus.DRAFT,
            draft_suggestions={
                "hypotheses": {
                    "H1": {
                        "metric_suggestions": [
                            {"metric_name": "营业收入同比", "rationale": "观察收入增速"}
                        ]
                    }
                },
                "risks": [{"statement": "需求回落"}],
            },
        )
    )
    for hypothesis_id in ("H1", "H2"):
        uow.thesis.add_hypothesis(
            HypothesisRecord(
                hypothesis_id=hypothesis_id,
                thesis_id="THS-CONFIG-1",
                statement=f"假设 {hypothesis_id}",
                hypothesis_type="经营",
                importance=Importance.SUPPORTING,
            )
        )
    return uow


def test_thesis_summary_list_does_not_expand_hypotheses() -> None:
    uow = _draft_uow()
    application = create_app()
    application.dependency_overrides[get_uow] = lambda: uow

    with TestClient(application) as client:
        response = client.get(
            "/api/theses/summaries?limit=100", headers={"X-User-Id": "analyst-mvp"}
        )

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "thesis_id": "THS-CONFIG-1",
            "security_id": "DEMO001",
            "title": "网页发布闭环",
            "status": "草稿",
            "owner": "analyst-mvp",
            "direction": "观察",
            "thesis_kind": "canonical",
            "thesis_series_id": None,
        }
    ]
    application.dependency_overrides.clear()


def test_researcher_can_configure_draft_and_publish_without_database_scripts() -> None:
    uow = _draft_uow()
    application = create_app()
    application.dependency_overrides[get_uow] = lambda: uow
    headers = {"X-User-Id": "analyst-mvp"}
    try:
        with TestClient(application) as client:
            detail = client.get("/api/theses/THS-CONFIG-1", headers=headers)
            assert detail.status_code == 200
            assert detail.json()["hypotheses"][0]["metric_suggestions"][0]["metric_name"] == (
                "营业收入同比"
            )

            thesis = client.patch(
                "/api/theses/THS-CONFIG-1",
                headers=headers,
                json={"title": "网页可编辑草稿", "core_view": "研究员调整后的核心观点"},
            )
            assert thesis.status_code == 200, thesis.text
            assert thesis.json()["title"] == "网页可编辑草稿"
            assert thesis.json()["core_view"] == "研究员调整后的核心观点"

            metrics = client.get("/api/metrics?keyword=收入", headers=headers)
            assert metrics.status_code == 200
            assert metrics.json()[0]["metric_id"] == "MET-DEMO-001"

            hypothesis = client.patch(
                "/api/theses/THS-CONFIG-1/hypotheses/H1",
                headers=headers,
                json={
                    "statement": "营业收入同比保持增长",
                    "hypothesis_type": "经营",
                    "importance": "核心",
                    "observation_window": "未来 4 个季度",
                    "invalidation_rule": "营业收入同比转负",
                },
            )
            assert hypothesis.status_code == 200, hypothesis.text

            mapping = client.post(
                "/api/theses/THS-CONFIG-1/hypotheses/H1/mappings",
                headers=headers,
                json={
                    "metric_id": "MET-DEMO-001",
                    "metric_version": "v1.0",
                    "expected_direction": "越高越好",
                    "expected_value": "15.0",
                    "invalidation_threshold": "0",
                    "invalidation_consecutive_periods": 2,
                    "expectation_source": "研究员人工判断",
                },
            )
            assert mapping.status_code == 200, mapping.text
            assert mapping.json()["expected_value"] == "15.0"

            today = date.today()
            publish_input = {
                "direction": "看多",
                "horizon_end_on": (today + timedelta(days=365)).isoformat(),
                "next_review_at": (today + timedelta(days=90)).isoformat(),
            }
            readiness = client.post(
                "/api/theses/THS-CONFIG-1/publish-readiness",
                headers=headers,
                json=publish_input,
            )
            assert readiness.status_code == 200, readiness.text
            assert readiness.json()["ready"] is True

            published = client.post(
                "/api/theses/THS-CONFIG-1/publish",
                headers=headers,
                json=publish_input,
            )
            assert published.status_code == 200, published.text
            assert published.json()["status"] == "验证中"
    finally:
        application.dependency_overrides.clear()

    snapshot = uow.versions.latest("THS-CONFIG-1")
    assert snapshot is not None
    assert snapshot.snapshot["metric_mappings"][0]["metric_id"] == "MET-DEMO-001"


def test_mapping_rejects_metric_outside_dictionary() -> None:
    uow = _draft_uow()
    application = create_app()
    application.dependency_overrides[get_uow] = lambda: uow
    try:
        with TestClient(application) as client:
            response = client.post(
                "/api/theses/THS-CONFIG-1/hypotheses/H1/mappings",
                headers={"X-User-Id": "analyst-mvp"},
                json={
                    "metric_id": "MET-NOT-EXISTS",
                    "expected_direction": "越高越好",
                    "expected_value": "1",
                    "expectation_source": "研究员人工判断",
                },
            )
        assert response.status_code == 400
        assert "指标字典" in response.json()["detail"]
    finally:
        application.dependency_overrides.clear()


def test_researcher_can_add_hypothesis_and_create_new_version() -> None:
    uow = _draft_uow()
    application = create_app()
    application.dependency_overrides[get_uow] = lambda: uow
    try:
        with TestClient(application) as client:
            response = client.post(
                "/api/theses/THS-CONFIG-1/hypotheses",
                headers={"X-User-Id": "analyst-mvp"},
                json={
                    "statement": "费用率继续下降",
                    "hypothesis_type": "盈利",
                    "importance": "核心",
                    "observation_window": "未来 4 个季度",
                    "invalidation_rule": "费用率连续两个季度上升",
                },
            )
        assert response.status_code == 201, response.text
        created = next(
            item for item in response.json()["hypotheses"] if item["statement"] == "费用率继续下降"
        )
        assert created["importance"] == "核心"
        assert created["observation_window"] == "未来 4 个季度"
    finally:
        application.dependency_overrides.clear()

    snapshot = uow.versions.latest("THS-CONFIG-1")
    assert snapshot is not None
    assert any(
        item["statement"] == "费用率继续下降" for item in snapshot.snapshot["hypotheses"]
    )


def test_duplicate_company_draft_returns_visible_existing_thesis_without_calling_model() -> None:
    uow = build_fake_uow()
    uow.securities.add(SecurityRecord(security_id="688981", name="中芯国际"))
    uow.thesis.add(
        ThesisRecord(
            thesis_id="THS-688981-MAIN",
            security_id="688981",
            title="公司级投资逻辑",
            direction="观察",
            core_view="只维护一条研究主线",
            established_on=date(2026, 8, 1),
            owner="analyst-mvp",
            status=ThesisStatus.VALIDATING,
            visibility=Visibility.PRIVATE,
        )
    )
    application = create_app()
    application.dependency_overrides[get_uow] = lambda: uow
    try:
        with TestClient(application) as client:
            response = client.post(
                "/api/theses/drafts",
                headers={"X-User-Id": "analyst-mvp"},
                json={"security_id": "688981", "view": "重复创建不应调用模型"},
            )
        assert response.status_code == 409
        assert response.json()["detail"] == {
            "code": "THESIS_ALREADY_EXISTS",
            "message": "该公司已维护一条投资逻辑，请打开现有逻辑进行修订",
            "thesis_id": "THS-688981-MAIN",
        }
    finally:
        application.dependency_overrides.clear()


def test_duplicate_company_conflict_does_not_disclose_hidden_thesis_id() -> None:
    uow = build_fake_uow()
    uow.securities.add(SecurityRecord(security_id="688981", name="中芯国际"))
    uow.thesis.add(
        ThesisRecord(
            thesis_id="THS-SECRET",
            security_id="688981",
            title="私有逻辑",
            direction="观察",
            core_view="研究覆盖本身属于敏感信息",
            established_on=date(2026, 8, 1),
            owner="other-researcher",
            status=ThesisStatus.VALIDATING,
            visibility=Visibility.PRIVATE,
        )
    )
    application = create_app()
    application.dependency_overrides[get_uow] = lambda: uow
    try:
        with TestClient(application) as client:
            response = client.post(
                "/api/theses/drafts",
                headers={"X-User-Id": "analyst-mvp"},
                json={"security_id": "688981", "view": "重复创建"},
            )
        assert response.status_code == 409
        assert "thesis_id" not in response.json()["detail"]
    finally:
        application.dependency_overrides.clear()
