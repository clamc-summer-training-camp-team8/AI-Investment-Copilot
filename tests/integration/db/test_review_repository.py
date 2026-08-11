from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.core.domain import ReviewTaskRecord
from app.core.timeutil import now
from app.db.models import Security, Thesis
from app.db.repositories.review import SqlReviewTaskRepo

pytestmark = pytest.mark.integration


def test_review_task_repository_round_trip(session: Session) -> None:
    session.add(Security(security_id="REVIEW001", name="复核测试公司", is_illustrative=True))
    session.add(
        Thesis(
            thesis_id="THS-REVIEW-001",
            security_id="REVIEW001",
            title="复核仓储测试",
            direction="观察",
            core_view="验证复核任务持久化",
            established_on=date(2026, 8, 11),
            owner="researcher-1",
            visibility="私有",
            status="草稿",
            version=0,
            is_illustrative=True,
        )
    )
    session.flush()
    repo = SqlReviewTaskRepo(session)

    created = repo.add(
        ReviewTaskRecord(
            task_id="RVW-INTEGRATION-001",
            thesis_id="THS-REVIEW-001",
            trigger="人工发起",
            priority="普通",
            assignee="researcher-1",
        )
    )
    created.state = "已完成"
    created.resolution = "公告原文与候选方向一致"
    created.resolved_at = now()
    repo.update(created)

    loaded = repo.get(created.task_id)
    assigned = repo.list_for_assignee("researcher-1", state="已完成")

    assert loaded is not None
    assert loaded.created_at is not None
    assert loaded.resolution == "公告原文与候选方向一致"
    assert [item.task_id for item in assigned] == [created.task_id]
