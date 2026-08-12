from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.api.deps import get_settings, get_uow
from app.api.main import create_app
from app.core.config import Settings
from app.db.repositories import build_uow

pytestmark = pytest.mark.integration


def test_api_persists_draft_and_review_task_in_postgres(engine: Engine) -> None:
    suffix = uuid4().hex[:10]
    security_id = f"API{suffix}".upper()
    headers = {"X-User-Id": "researcher-api"}
    with engine.begin() as connection:
        connection.execute(
            text(
                "insert into security (security_id, name, is_illustrative) "
                "values (:security_id, :name, true)"
            ),
            {"security_id": security_id, "name": "API 联调测试公司"},
        )

    application = create_app()
    application.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)

    def integration_uow():
        with (
            engine.begin() as connection,
            Session(bind=connection, expire_on_commit=False) as session,
        ):
            yield build_uow(session)

    application.dependency_overrides[get_uow] = integration_uow
    thesis_id = ""
    task_id = ""
    try:
        with TestClient(application) as client:
            draft = client.post(
                "/api/theses/drafts",
                headers=headers,
                json={
                    "security_id": security_id,
                    "view": "订单增长应当推动收入增长，毛利率保持稳定",
                },
            )
            assert draft.status_code == 201, draft.text
            thesis_id = draft.json()["thesis_id"]

            review = client.post(
                "/api/reviews",
                headers=headers,
                json={"thesis_id": thesis_id, "trigger": "人工发起", "priority": "高"},
            )
            assert review.status_code == 201, review.text
            task_id = review.json()["task_id"]

            resolved = client.post(
                f"/api/reviews/{task_id}/resolve",
                headers=headers,
                json={"resolution": "真实 PostgreSQL 联调完成"},
            )
            assert resolved.status_code == 200, resolved.text

        with engine.connect() as connection:
            stored = connection.execute(
                text("select state, resolution from review_task where task_id=:task_id"),
                {"task_id": task_id},
            ).one()
        assert stored == ("已完成", "真实 PostgreSQL 联调完成")
    finally:
        application.dependency_overrides.clear()
        with engine.begin() as connection:
            if task_id:
                connection.execute(
                    text("delete from audit_log where object_id=:task_id"), {"task_id": task_id}
                )
                connection.execute(
                    text("delete from review_task where task_id=:task_id"), {"task_id": task_id}
                )
            if thesis_id:
                connection.execute(
                    text("delete from audit_log where object_id=:thesis_id"),
                    {"thesis_id": thesis_id},
                )
                connection.execute(
                    text("delete from hypothesis where thesis_id=:thesis_id"),
                    {"thesis_id": thesis_id},
                )
                connection.execute(
                    text("delete from thesis where thesis_id=:thesis_id"),
                    {"thesis_id": thesis_id},
                )
            connection.execute(
                text("delete from security where security_id=:security_id"),
                {"security_id": security_id},
            )
