from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime

from fastapi.testclient import TestClient

from app.api.deps import get_settings, get_uow
from app.api.main import create_app
from app.core.config import Settings
from app.core.domain import HypothesisRecord, SecurityRecord, ThesisRecord, VersionRecord
from app.core.enums import Importance
from tests.fakes import build_fake_uow


@contextmanager
def _client() -> Iterator[TestClient]:
    uow = build_fake_uow()
    thesis = ThesisRecord(
        thesis_id="THS-API-RETRO",
        security_id="0175.HK",
        title="API 复盘逻辑",
        direction="观察",
        core_view="只使用历史时点来源。",
        established_on=date(2025, 1, 1),
        owner="analyst",
        visibility="团队",
        team="alpha",
    )
    uow.securities.add(SecurityRecord(thesis.security_id, "吉利汽车"))
    uow.thesis.add(thesis)
    uow.thesis.add_hypothesis(
        HypothesisRecord(
            hypothesis_id="THS-API-RETRO-H1",
            thesis_id=thesis.thesis_id,
            statement="销量增长",
            hypothesis_type="经营",
            importance=Importance.CORE,
        )
    )
    uow.versions.add(
        VersionRecord(
            thesis_id=thesis.thesis_id,
            version=1,
            snapshot={"core_view": thesis.core_view},
            triggered_by="发布",
            created_by="analyst",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    app = create_app()
    app.dependency_overrides[get_uow] = lambda: uow
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, retrospective_center_enabled=True
    )
    try:
        with TestClient(app, headers={"X-User-Id": "analyst", "X-User-Teams": "alpha"}) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def test_retrospective_api_preview_create_list_and_detail() -> None:
    with _client() as client:
        timebox = {
            "thesis_id": "THS-API-RETRO",
            "period_start": "2026-01-01",
            "period_end": "2026-06-30",
            "data_cutoff_at": "2026-06-30T15:59:00Z",
        }
        preview = client.post("/api/retrospectives/source-preview", json=timebox)
        assert preview.status_code == 200
        assert preview.json()["source_count"] == 1

        created = client.post(
            "/api/retrospectives",
            json={
                **timebox,
                "retrospective_type": "周期",
                "title": "API 年中复盘",
            },
        )
        assert created.status_code == 201
        retrospective_id = created.json()["retrospective_id"]
        listing = client.get("/api/retrospectives")
        assert listing.status_code == 200
        assert listing.json()["total"] == 1
        detail = client.get(f"/api/retrospectives/{retrospective_id}")
        assert detail.status_code == 200
        assert "edit" in detail.json()["allowed_actions"]
        assert detail.json()["retrospective"]["lock_version"] == 1

        content = detail.json()["content"]
        content.update(
            {
                "summary": "API 主链人工复盘。",
                "errors_and_omissions": "仍需补充盈利披露。",
                "limitations": "只使用截止时点前来源。",
                "next_actions": "继续跟踪销量和盈利。",
            }
        )
        content["hypothesis_assessments"][0]["rationale"] = "现有证据仍不足。"
        saved = client.patch(
            f"/api/retrospectives/{retrospective_id}/draft",
            json={"lock_version": 1, "content": content},
        )
        assert saved.status_code == 200
        assert saved.json()["lock_version"] == 2
        published = client.post(
            f"/api/retrospectives/{retrospective_id}/publish",
            json={"lock_version": 2, "publish_reason": "API 主链验收"},
        )
        assert published.status_code == 200
        assert published.json()["state"] == "已发布"
        assert published.json()["current_version"] == 1
        exported = client.get(f"/api/retrospectives/{retrospective_id}/exports/json")
        assert exported.status_code == 200
        assert exported.json()["content"]["summary"] == "API 主链人工复盘。"
