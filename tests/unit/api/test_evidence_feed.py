"""可读证据聚合接口：固定页面不再依赖裸 ID 拼装研究信息。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app.api.deps import get_uow
from app.api.main import create_app
from app.core.domain import EvidenceFeedRecord, ThesisRecord, UnitOfWork
from app.core.enums import ConfirmationStatus, ImpactDirection, Importance, ThesisStatus
from tests.fakes import build_fake_uow

HEADERS = {"X-User-Id": "analyst-a", "X-User-Teams": "equity-research"}


@contextmanager
def _client() -> Iterator[TestClient]:
    app = create_app()
    uow = build_fake_uow()
    uow.thesis.add(
        ThesisRecord(
            thesis_id="THS-001",
            security_id="688981",
            title="中芯国际盈利观察",
            direction="观察",
            core_view="观察产能利用率与毛利率",
            established_on=date(2026, 1, 1),
            owner="analyst-a",
            status=ThesisStatus.VALIDATING,
            team="equity-research",
        )
    )
    uow.feed.items.append(
        EvidenceFeedRecord(
            evidence_id="EVD-001",
            relation_id="REL-001",
            security_id="688981",
            security_name="中芯国际",
            thesis_id="THS-001",
            thesis_title="中芯国际盈利观察",
            thesis_owner="analyst-a",
            thesis_status=ThesisStatus.VALIDATING,
            thesis_established_on=date(2026, 1, 1),
            thesis_horizon_end_on=None,
            hypothesis_id="H-001",
            hypothesis_statement="毛利率随利用率回升",
            hypothesis_importance=Importance.CORE,
            source_document_id="DOC-001",
            source_document_title="2025 年第四季度业绩快报",
            fact_excerpt="公司披露第四季度经营数据。",
            disclosed_at=datetime(2026, 2, 11),
            occurred_at=date(2025, 12, 31),
            source_url="https://example.com/report.pdf",
            direction=ImpactDirection.NEUTRAL,
            strength="中",
            ai_confidence=Decimal("0.70"),
            confirmation_status=ConfirmationStatus.PENDING,
            priority="medium",
        )
    )

    def _uow() -> Iterator[UnitOfWork]:
        yield uow

    app.dependency_overrides[get_uow] = _uow
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_工作台任务返回可读证据与验证链() -> None:
    with _client() as client:
        response = client.get("/api/workbench/tasks", headers=HEADERS)
        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["source_document_title"] == "2025 年第四季度业绩快报"
        assert item["hypothesis_statement"] == "毛利率随利用率回升"
        assert item["evidence_id"] == "EVD-001"
        assert {validation["code"] for validation in item["validation_items"]} == {
            "source_traceable",
            "required_fields_complete",
            "within_observation_window",
            "same_security",
            "hypothesis_belongs_to_thesis",
        }


def test_雷达必须携带明确逻辑上下文() -> None:
    with _client() as client:
        assert client.get("/api/radar/evidence", headers=HEADERS).status_code == 422
        response = client.get(
            "/api/radar/evidence", params={"thesis_id": "THS-001"}, headers=HEADERS
        )
        assert response.status_code == 200
        assert response.json()["page"]["total"] == 1
