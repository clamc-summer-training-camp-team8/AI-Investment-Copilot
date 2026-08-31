from __future__ import annotations

from collections.abc import Iterator
from datetime import date

from fastapi.testclient import TestClient

from app.api.deps import get_uow
from app.api.main import create_app
from app.core.domain import ThesisRecord, UnitOfWork
from tests.fakes import build_fake_uow


def _uow() -> UnitOfWork:
    uow = build_fake_uow()
    uow.thesis.add(
        ThesisRecord(
            thesis_id="THS-API-REVIEW",
            security_id="600000.SH",
            title="复核接口测试",
            direction="观察",
            core_view="验证复核接口",
            established_on=date(2026, 8, 11),
            owner="researcher-1",
            visibility="私有",
        )
    )
    return uow


def test_review_center_create_list_and_resolve() -> None:
    uow = _uow()
    application = create_app()

    def override_uow() -> Iterator[UnitOfWork]:
        yield uow

    application.dependency_overrides[get_uow] = override_uow
    headers = {"X-User-Id": "researcher-1"}

    with TestClient(application) as client:
        created = client.post(
            "/api/reviews",
            headers=headers,
            json={"thesis_id": "THS-API-REVIEW", "trigger": "人工发起"},
        )
        assert created.status_code == 201, created.text
        task_id = created.json()["task_id"]

        listed = client.get("/api/reviews", headers=headers)
        assert listed.status_code == 200
        assert [item["task_id"] for item in listed.json()] == [task_id]

        resolved = client.post(
            f"/api/reviews/{task_id}/resolve",
            headers=headers,
            json={"resolution": "已核对公告原文，结论正确"},
        )
        assert resolved.status_code == 200
        assert resolved.json()["state"] == "已完成"

    application.dependency_overrides.clear()
