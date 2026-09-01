from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.core.domain import (
    RetrospectiveQuery,
    RetrospectiveRecord,
    RetrospectiveSourceRecord,
    RetrospectiveVersionRecord,
    SecurityRecord,
    ThesisRecord,
)
from app.db.repositories import build_uow


def test_retrospective_repository_roundtrip_visibility_and_optimistic_lock(
    session: Session,
) -> None:
    suffix = uuid4().hex[:10]
    security_id = f"RT-{suffix}"
    thesis_id = f"THS-RT-{suffix}"
    retrospective_id = f"RTP-{suffix}"
    uow = build_uow(session)
    uow.securities.add(SecurityRecord(security_id, "复盘仓储测试"))
    uow.thesis.add(
        ThesisRecord(
            thesis_id=thesis_id,
            security_id=security_id,
            title="复盘仓储逻辑",
            direction="观察",
            core_view="验证不可变来源与版本。",
            established_on=date(2026, 1, 1),
            owner="owner",
            visibility="团队",
            team="alpha",
        )
    )
    record = RetrospectiveRecord(
        retrospective_id=retrospective_id,
        thesis_id=thesis_id,
        retrospective_type="周期",
        title="仓储往返复盘",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 6, 30),
        data_cutoff_at=datetime(2026, 6, 30, 15, 59, tzinfo=UTC),
        owner="owner",
        visibility="团队",
        team="alpha",
        source_fingerprint="a" * 64,
        source_count=1,
        completeness_completed=3,
        completeness_applicable=3,
        completeness_score=Decimal("1"),
        draft_content={"summary": "草稿"},
    )
    stored = uow.retrospectives.add(record)
    uow.retrospectives.add_sources(
        [
            RetrospectiveSourceRecord(
                source_id=f"RCS-{uuid4().hex[:24]}",
                retrospective_id=retrospective_id,
                source_type="thesis_version",
                object_id=thesis_id,
                object_version="1",
                summary="V1 · 发布",
            )
        ]
    )
    assert stored.lock_version == 1
    owner_rows, owner_total = uow.retrospectives.search_visible(
        actor_id="owner", teams=(), query=RetrospectiveQuery()
    )
    assert owner_total == 1
    assert owner_rows[0].retrospective_id == retrospective_id
    _, hidden_total = uow.retrospectives.search_visible(
        actor_id="colleague", teams=("alpha",), query=RetrospectiveQuery()
    )
    assert hidden_total == 0

    published = RetrospectiveRecord(
        **{
            **stored.__dict__,
            "state": "已发布",
            "current_version": 1,
            "lock_version": 2,
        }
    )
    uow.retrospectives.update(published, expected_lock_version=1)
    uow.retrospectives.add_version(
        RetrospectiveVersionRecord(
            retrospective_id=retrospective_id,
            version=1,
            content={"summary": "正式版本"},
            source_fingerprint="a" * 64,
            published_by="owner",
            publish_reason="集成测试",
        )
    )
    with pytest.raises(RuntimeError, match="retrospective_lock_conflict"):
        uow.retrospectives.update(published, expected_lock_version=1)
    team_rows, team_total = uow.retrospectives.search_visible(
        actor_id="colleague", teams=("alpha",), query=RetrospectiveQuery()
    )
    assert team_total == 1
    assert team_rows[0].state == "已发布"
    revision_draft = RetrospectiveRecord(
        **{
            **published.__dict__,
            "draft_content": {
                "summary": "未发布修订秘密",
                "hypothesis_assessments": [{"result": "不成立"}],
            },
            "lock_version": 3,
        }
    )
    uow.retrospectives.update(revision_draft, expected_lock_version=2)
    _, leaked_text_total = uow.retrospectives.search_visible(
        actor_id="colleague",
        teams=("alpha",),
        query=RetrospectiveQuery(query="未发布修订秘密"),
    )
    _, leaked_result_total = uow.retrospectives.search_visible(
        actor_id="colleague",
        teams=("alpha",),
        query=RetrospectiveQuery(hypothesis_result="不成立"),
    )
    _, owner_draft_total = uow.retrospectives.search_visible(
        actor_id="owner",
        teams=(),
        query=RetrospectiveQuery(query="未发布修订秘密"),
    )
    assert leaked_text_total == 0
    assert leaked_result_total == 0
    assert owner_draft_total == 1
    assert uow.retrospectives.get_version(retrospective_id, 1).content == {  # type: ignore[union-attr]
        "summary": "正式版本"
    }
    assert uow.retrospectives.list_sources(retrospective_id)[0].object_version == "1"
