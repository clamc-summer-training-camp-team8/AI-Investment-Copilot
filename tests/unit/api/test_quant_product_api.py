from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime

from fastapi.testclient import TestClient

from app.api.deps import get_settings, get_uow
from app.api.main import create_app
from app.core.config import Settings
from app.core.domain import EvidenceRecord, EvidenceRelationRecord, ThesisRecord, UnitOfWork
from app.core.enums import ConfirmationStatus, ImpactDirection
from app.core.timeutil import BUSINESS_TZ
from tests.fakes import build_fake_uow


def _client() -> tuple[TestClient, UnitOfWork]:
    uow = build_fake_uow()
    uow.thesis.add(
        ThesisRecord(
            thesis_id="THS-QUANT",
            security_id="688981",
            title="量化信号来源逻辑",
            direction="正向",
            core_view="只用于量化信号来源权限测试",
            established_on=date(2024, 1, 1),
            owner="quant-researcher",
            visibility="私有",
        )
    )
    disclosed = datetime(2024, 3, 1, 18, tzinfo=BUSINESS_TZ)
    confirmed = datetime(2024, 3, 1, 18, 4, tzinfo=BUSINESS_TZ)
    for evidence_id, security_id, direction in (
        ("EVD-688981", "688981", ImpactDirection.SUPPORT),
        ("EVD-603986", "603986", ImpactDirection.SUPPORT),
        ("EVD-002371", "002371", ImpactDirection.CONFLICT),
        ("EVD-CAP", "688981", ImpactDirection.SUPPORT),
    ):
        uow.evidence.add(
            EvidenceRecord(
                evidence_id=evidence_id,
                thesis_id="THS-QUANT",
                hypothesis_id="HYP-QUANT",
                evidence_type="事件",
                direction=direction,
                evidence_locator=f"DOC-QUANT#{evidence_id}",
                confirmation_status=ConfirmationStatus.CONFIRMED,
                confirmed_by="quant-reviewer",
                confirmed_at=confirmed,
                security_id=security_id,
                disclosed_at=disclosed,
            )
        )
        uow.relations.add(
            EvidenceRelationRecord(
                relation_id=f"REL-{security_id}" if evidence_id != "EVD-CAP" else "REL-CAP",
                evidence_id=evidence_id,
                thesis_id="THS-QUANT",
                hypothesis_id="HYP-QUANT",
                direction=direction,
                strength="高",
                status=ConfirmationStatus.CONFIRMED,
                created_by="quant-reviewer",
                reviewed_by="quant-reviewer",
                reviewed_at=confirmed,
            )
        )
    app = create_app()

    def override() -> Iterator[UnitOfWork]:
        yield uow

    app.dependency_overrides[get_uow] = override
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        quant_dataset_api_registration_enabled=True,
    )
    return TestClient(
        app,
        headers={"X-User-Id": "quant-researcher", "X-User-Teams": "quant-governance"},
    ), uow


def test_冻结行情信号组合运行和历史查询形成持久闭环() -> None:
    client, _ = _client()
    with client:
        dataset_response = client.post("/api/quant/market-datasets/register-default")
        assert dataset_response.status_code == 200
        dataset = dataset_response.json()
        assert dataset["status"] == "frozen"

        dataset_detail = client.get(f"/api/quant/market-datasets/{dataset['dataset_id']}")
        assert dataset_detail.status_code == 200
        assert dataset_detail.json()["security_metadata"]

        signals = {
            "name": "人工确认事件方向",
            "version": "confirmed-signals-test-v1",
            "signals": [
                {
                    "signal_id": f"SIG-{security_id}",
                    "security_id": security_id,
                    "disclosed_at": "2024-03-01T18:00:00+08:00",
                    "generated_at": "2024-03-01T18:05:00+08:00",
                    "direction": direction,
                    "strength": "高",
                    "confidence": "0.8",
                    "confirmation_status": "已确认",
                    "source_evidence_id": f"EVD-{security_id}",
                    "source_relation_id": f"REL-{security_id}",
                }
                for security_id, direction in (
                    ("688981", "支持"),
                    ("603986", "支持"),
                    ("002371", "冲突"),
                )
            ],
        }
        signal_response = client.post("/api/quant/signal-sets", json=signals)
        assert signal_response.status_code == 200
        signal_set = signal_response.json()
        assert signal_set["evaluation_track"] == "alpha_validation"
        signal_detail = client.get(f"/api/quant/signal-sets/{signal_set['signal_set_id']}")
        assert signal_detail.status_code == 200
        detail = signal_detail.json()
        assert detail["visible_signal_count"] == 3
        assert all(not item["confidence_used_for_alpha_weight"] for item in detail["signals"])
        assert {item["source_evidence_id"] for item in detail["signals"]} == {
            "EVD-688981",
            "EVD-603986",
            "EVD-002371",
        }

        run_response = client.post(
            "/api/quant/portfolio-backtests",
            json={
                "name": "半导体组合样本外研究",
                "market_dataset_id": dataset["dataset_id"],
                "signal_set_id": signal_set["signal_set_id"],
                "security_ids": ["688981", "603986", "002371"],
                "start": "2024-01-01",
                "end": "2025-06-30",
                "config": {
                    "rolling_window_days": 20,
                    "walk_forward_days": 20,
                    "rebalance_days": 5,
                    "neutralize_industry": False,
                    "neutralize_market_cap": False,
                    "enforce_capacity": True,
                },
            },
        )
        assert run_response.status_code == 200, run_response.text
        run = run_response.json()
        assert run["run_id"].startswith("QPF-")
        assert run["methodology_version"] == "portfolio-research-v3"
        assert run["parameters"]["model_template_id"] == "confirmed-event-research-v3"
        assert run["parameters"]["model_template_version"] == "3.0.0"
        assert run["parameters"]["factor_versions"] == {
            "adv20_capacity": "1.0.0",
            "confirmed_event_direction_strength": "1.0.0",
            "industry_neutralization": "1.0.0",
            "point_in_time_market_cap_rank": "1.0.0",
        }
        assert run["parameters"]["ai_confidence_used_for_alpha_weight"] is False
        assert run["result"]["validation_quality"]["alpha_claim_allowed"] is False
        assert run["result"]["walk_forward"]
        assert "risk_attribution" in run["result"]

        history = client.get("/api/quant/portfolio-backtests")
        assert history.status_code == 200
        assert [item["run_id"] for item in history.json()] == [run["run_id"]]
        detail = client.get(f"/api/quant/portfolio-backtests/{run['run_id']}")
        assert detail.status_code == 200

        catalog = client.get("/api/quant/catalog").json()
        assert catalog["default_market_dataset_id"] == dataset["dataset_id"]
        assert catalog["evaluation_separation"]["alpha_validation"] == "alpha_validation"
        assert "不得替代" in catalog["evaluation_separation"]["hard_rule"]

        factors = client.get("/api/quant/factors")
        assert factors.status_code == 200
        factor_status = {item["factor_id"]: item["status"] for item in factors.json()}
        assert factor_status["confirmed_event_direction_strength"] == "active"
        assert factor_status["industry_neutralization"] == "gated"
        assert factor_status["momentum_20_60_120"] == "planned"
        assert {item["version"] for item in factors.json()} == {"1.0.0"}

        templates = client.get("/api/quant/model-templates")
        assert templates.status_code == 200
        template_status = {item["template_id"]: item["status"] for item in templates.json()}
        assert template_status == {
            "confirmed-event-research-v3": "active",
            "confirmed-event-industry-neutral-v3": "gated",
            "event-momentum-overlay-v1": "planned",
        }
        planned = client.post(
            "/api/quant/portfolio-backtests",
            json={
                "market_dataset_id": dataset["dataset_id"],
                "signal_set_id": signal_set["signal_set_id"],
                "model_template_id": "event-momentum-overlay-v1",
                "security_ids": ["688981", "603986", "002371"],
            },
        )
        assert planned.status_code == 422
        assert "尚未发布" in planned.json()["detail"]


def test_市值中性在缺点时市值的数据集上被能力门禁拒绝() -> None:
    client, _ = _client()
    with client:
        dataset = client.post("/api/quant/market-datasets/register-default").json()
        signal_set = client.post(
            "/api/quant/signal-sets",
            json={
                "name": "确认信号",
                "version": "cap-gate-v1",
                "signals": [
                    {
                        "signal_id": "SIG-CAP",
                        "security_id": "688981",
                        "disclosed_at": "2024-03-01T18:00:00+08:00",
                        "generated_at": "2024-03-01T18:05:00+08:00",
                        "direction": "支持",
                        "strength": "高",
                        "confidence": "1",
                        "confirmation_status": "已确认",
                        "source_evidence_id": "EVD-CAP",
                        "source_relation_id": "REL-CAP",
                    }
                ],
            },
        ).json()
        response = client.post(
            "/api/quant/portfolio-backtests",
            json={
                "market_dataset_id": dataset["dataset_id"],
                "signal_set_id": signal_set["signal_set_id"],
                "security_ids": ["688981"],
                "config": {"neutralize_market_cap": True},
            },
        )
        assert response.status_code == 422
        assert "点时市值" in response.json()["detail"]


def test_信号详情和数据登记均执行权限边界() -> None:
    client, _ = _client()
    with client:
        signal_set = client.post(
            "/api/quant/signal-sets",
            json={
                "name": "私有逻辑确认信号",
                "version": "private-signal-v1",
                "signals": [
                    {
                        "signal_id": "SIG-PRIVATE",
                        "security_id": "688981",
                        "disclosed_at": "2024-03-01T18:00:00+08:00",
                        "generated_at": "2024-03-01T18:05:00+08:00",
                        "direction": "支持",
                        "strength": "高",
                        "confidence": "0.8",
                        "confirmation_status": "已确认",
                        "source_evidence_id": "EVD-688981",
                        "source_relation_id": "REL-688981",
                    }
                ],
            },
        ).json()
        hidden = client.get(
            f"/api/quant/signal-sets/{signal_set['signal_set_id']}",
            headers={"X-User-Id": "another-researcher"},
        )
        assert hidden.status_code == 404

        forbidden = client.post(
            "/api/quant/market-datasets/register-default",
            headers={"X-User-Id": "ordinary-researcher", "X-User-Teams": "ordinary-team"},
        )
        assert forbidden.status_code == 403


def test_量化功能开关关闭时统一隐藏路由() -> None:
    client, uow = _client()
    app = create_app()

    def override() -> Iterator[UnitOfWork]:
        yield uow

    app.dependency_overrides[get_uow] = override
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        quant_research_enabled=False,
    )
    with TestClient(app, headers={"X-User-Id": "quant-researcher"}) as disabled:
        response = disabled.get("/api/quant/catalog")
    assert response.status_code == 404
    assert response.json()["detail"] == "模型与因子模块未启用"


def test_答辩演示情景由独立开关控制且不依赖数据库写入() -> None:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        quant_demo_enabled=True,
    )
    with TestClient(app, headers={"X-User-Id": "quant-researcher"}) as enabled:
        response = enabled.get("/api/quant/demo-scenario")

    assert response.status_code == 200
    body = response.json()
    assert body["evaluation_track"] == "scenario_simulation"
    assert body["dataset"]["security_count"] == 30
    assert body["summary"]["assumed_confirmed_count"] == 330
    assert body["summary"]["neutral_noop_count"] == 66
    assert body["result"]["validation_quality"]["unique_security_count"] == 30
    assert body["result"]["validation_quality"]["alpha_claim_allowed"] is False

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        quant_demo_enabled=False,
    )
    with TestClient(app, headers={"X-User-Id": "quant-researcher"}) as disabled:
        hidden = disabled.get("/api/quant/demo-scenario")
    assert hidden.status_code == 404
    assert hidden.json()["detail"] == "量化答辩演示情景未启用"
