from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.deps import get_settings
from app.api.main import create_app
from app.api.routers import jobs as jobs_router
from app.core.config import Settings


class FakeRedis:
    async def aclose(self) -> None:
        return None


def test_upload_document_enqueues_background_job(tmp_path: Path, monkeypatch) -> None:
    conf = Settings(_env_file=None, storage_dir=tmp_path)
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: conf
    captured: dict[str, object] = {}

    async def fake_open_queue(settings: Settings) -> FakeRedis:
        assert settings.storage_dir == tmp_path
        return FakeRedis()

    async def fake_enqueue(redis: FakeRedis, **kwargs: object) -> str:
        captured.update(kwargs)
        return "document-DOC-TEST"

    monkeypatch.setattr(jobs_router, "open_queue", fake_open_queue)
    monkeypatch.setattr(jobs_router, "enqueue_document", fake_enqueue)

    with TestClient(application) as client:
        response = client.post(
            "/api/jobs/documents",
            headers={"X-User-Id": "researcher-1"},
            files={"file": ("report.txt", "公开资料正文", "text/plain")},
        )

    assert response.status_code == 202, response.text
    assert response.json()["job_id"] == "document-DOC-TEST"
    saved = Path(str(captured["path"]))
    assert saved.is_file()
    assert saved.read_text(encoding="utf-8") == "公开资料正文"
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
