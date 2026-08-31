from __future__ import annotations

from datetime import date

import pytest

from app.core.domain import ThesisRecord
from app.services.errors import NotVisible, ValidationFailed
from app.services.permission import Actor
from app.services.review import create_task, get_assigned, list_assigned, resolve
from tests.fakes import build_fake_uow


def _uow():
    uow = build_fake_uow()
    uow.thesis.add(
        ThesisRecord(
            thesis_id="THS-1",
            security_id="600000.SH",
            title="测试逻辑",
            direction="观察",
            core_view="测试观点",
            established_on=date(2026, 8, 11),
            owner="researcher-1",
        )
    )
    return uow


def test_review_task_create_list_and_resolve() -> None:
    uow = _uow()
    actor = Actor(user_id="researcher-1")

    task = create_task(
        uow,
        thesis_id="THS-1",
        trigger="人工发起",
        priority="普通",
        assignee=actor.user_id,
        actor=actor,
    )
    completed = resolve(
        uow,
        task_id=task.task_id,
        actor=actor,
        resolution="已核对公告原文，方向正确",
    )

    assert len(list_assigned(uow, actor=actor)) == 1
    assert completed.state == "已完成"
    assert completed.resolved_at is not None


def test_review_task_is_hidden_from_another_user() -> None:
    uow = _uow()
    owner = Actor(user_id="researcher-1")
    task = create_task(
        uow,
        thesis_id="THS-1",
        trigger="人工发起",
        priority="普通",
        assignee=owner.user_id,
        actor=owner,
    )

    with pytest.raises(NotVisible):
        get_assigned(uow, task_id=task.task_id, actor=Actor(user_id="researcher-2"))


def test_review_task_cannot_be_resolved_twice() -> None:
    uow = _uow()
    actor = Actor(user_id="researcher-1")
    task = create_task(
        uow,
        thesis_id="THS-1",
        trigger="人工发起",
        priority="普通",
        assignee=actor.user_id,
        actor=actor,
    )
    resolve(uow, task_id=task.task_id, actor=actor, resolution="第一次完成")

    with pytest.raises(ValidationFailed):
        resolve(uow, task_id=task.task_id, actor=actor, resolution="重复完成")
