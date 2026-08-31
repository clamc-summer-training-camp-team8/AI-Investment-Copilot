from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

from fastapi.testclient import TestClient

from app.api.deps import get_uow
from app.api.main import create_app
from app.core.domain import EvidenceRecord, EvidenceRelationRecord, UnitOfWork
from app.core.enums import ConfirmationStatus, ImpactDirection
from app.core.timeutil import BUSINESS_TZ
from tests.fakes import build_fake_uow


def _client() -> tuple[TestClient, UnitOfWork]:
    uow = build_fake_uow()
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
    return TestClient(app, headers={"X-User-Id": "quant-researcher"}), uow


def test_冻结行情信号组合运行和历史查询形成持久闭环() -> None:
    client, _ = _client()
    with client:
        dataset_response = client.post("/api/quant/market-datasets/register-default")
        assert dataset_response.status_code == 200
        dataset = dataset_response.json()
        assert dataset["status"] == "frozen"

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
