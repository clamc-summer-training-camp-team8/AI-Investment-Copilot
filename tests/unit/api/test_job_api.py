from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.deps import get_settings, get_uow
from app.api.main import create_app
from app.api.routers import jobs as jobs_router
from app.core.config import Settings
from tests.fakes import build_fake_uow


class FakeRedis:
    async def get(self, key: str) -> bytes:
        return b"healthy"

    async def aclose(self) -> None:
        return None


class FakeObjectStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def ensure_bucket(self) -> None:
        return None

    def put_immutable(self, *, path: Path, object_key: str, content_hash: str, media_type: str):
        from app.services.object_store import StoredObject

        return StoredObject(object_key=object_key, version_id="version-1", etag="etag")


def test_upload_document_enqueues_background_job(tmp_path: Path, monkeypatch) -> None:
    conf = Settings(_env_file=None, storage_dir=tmp_path)
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: conf
    application.dependency_overrides[get_uow] = lambda: build_fake_uow()
    captured: dict[str, object] = {}

    async def fake_open_queue(settings: Settings) -> FakeRedis:
        assert settings.storage_dir == tmp_path
        return FakeRedis()

    async def fake_enqueue(redis: FakeRedis, **kwargs: object) -> str:
        captured.update(kwargs)
        return "document-DOC-TEST"

    monkeypatch.setattr(jobs_router, "open_queue", fake_open_queue)
    monkeypatch.setattr(jobs_router, "enqueue_document", fake_enqueue)
    monkeypatch.setattr(jobs_router, "S3ObjectStore", FakeObjectStore)

    with TestClient(application) as client:
        response = client.post(
            "/api/jobs/documents",
            headers={"X-User-Id": "researcher-1"},
            files={"file": ("report.txt", "公开资料正文", "text/plain")},
        )

    assert response.status_code == 202, response.text
    assert response.json()["job_id"] == "document-DOC-TEST"
    assert captured["path"] == ""
    assert str(captured["object_key"]).endswith(".txt")
    assert captured["object_version_id"] == "version-1"
    assert not any((tmp_path / "uploads").glob("*.txt"))
    application.dependency_overrides.clear()


def test_upload_document_rejects_unsafe_metadata(tmp_path: Path) -> None:
    conf = Settings(_env_file=None, storage_dir=tmp_path)
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: conf

    with TestClient(application) as client:
        naive_time = client.post(
            "/api/jobs/documents",
            headers={"X-User-Id": "researcher-1"},
            files={"file": ("report.txt", "正文", "text/plain")},
            data={"published_at": "2026-08-11T09:00:00"},
        )
        incomplete_link = client.post(
            "/api/jobs/documents",
            headers={"X-User-Id": "researcher-1"},
            files={"file": ("report.txt", "正文", "text/plain")},
            data={"thesis_id": "THS-1"},
        )

    assert naive_time.status_code == 422
    assert incomplete_link.status_code == 422
    assert not (tmp_path / "uploads").exists()
    application.dependency_overrides.clear()
