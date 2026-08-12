from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.deps import get_uow
from app.api.main import create_app
from tests.fakes import build_fake_uow


def test_security_creation_requires_master_data_role() -> None:
    application = create_app()
    application.dependency_overrides[get_uow] = lambda: build_fake_uow()
    with TestClient(application) as client:
        denied = client.post(
            "/api/securities",
            headers={"X-User-Id": "ordinary-researcher"},
            json={"security_id": "NEW001", "name": "新公司"},
        )
        allowed = client.post(
            "/api/securities",
            headers={"X-User-Id": "ordinary-researcher", "X-User-Teams": "security-admin"},
            json={"security_id": "NEW001", "name": "新公司"},
        )

    assert denied.status_code == 403
    assert allowed.status_code == 201
    application.dependency_overrides.clear()
