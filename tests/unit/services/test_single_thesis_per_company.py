from __future__ import annotations

from datetime import date

import pytest

from app.core.domain import ThesisQuery, ThesisRecord
from app.core.enums import ThesisStatus
from app.services import thesis as thesis_service
from app.services.errors import ThesisAlreadyExists
from app.services.permission import Actor
from tests.fakes import build_fake_uow


def _existing(*, visibility: str = "团队", team: str | None = "权益研究") -> ThesisRecord:
    return ThesisRecord(
        thesis_id="THS-688981-MAIN",
        security_id="688981",
        title="中芯国际公司级投资逻辑",
        direction="观察",
        core_view="通过版本化修订维护公司级研究主线",
        established_on=date(2026, 8, 1),
        owner="研究员A",
        status=ThesisStatus.VALIDATING,
        visibility=visibility,
        team=team,
    )


def _draft() -> dict[str, object]:
    return {
        "security_id": "688981",
        "title": "重复逻辑",
        "core_view": "不应创建第二条公司级逻辑",
        "hypotheses": [
            {"statement": "需求回升", "importance": "核心"},
            {"statement": "盈利改善", "importance": "辅助"},
        ],
    }


def test_company_can_only_create_one_thesis_and_visible_conflict_links_existing() -> None:
    uow = build_fake_uow()
    uow.thesis.add(_existing())

    with pytest.raises(ThesisAlreadyExists) as caught:
        thesis_service.create_draft(
            uow,
            thesis_id="THS-688981-DUPLICATE",
            draft=_draft(),
            actor=Actor(user_id="研究员B", teams=frozenset({"权益研究"})),
        )

    assert caught.value.thesis_id == "THS-688981-MAIN"
    assert uow.thesis.get_by_security("688981") is not None


def test_hidden_existing_thesis_blocks_duplicate_without_disclosing_identifier() -> None:
    uow = build_fake_uow()
    uow.thesis.add(_existing(visibility="私有", team=None))

    with pytest.raises(ThesisAlreadyExists) as caught:
        thesis_service.create_draft(
            uow,
            thesis_id="THS-688981-DUPLICATE",
            draft=_draft(),
            actor=Actor(user_id="研究员B"),
        )

    assert caught.value.thesis_id is None


def test_superseded_theses_remain_as_history_but_are_not_in_current_company_list() -> None:
    uow = build_fake_uow()
    current = _existing()
    uow.thesis.add(current)
    uow.thesis.add(
        ThesisRecord(
            thesis_id="THS-688981-2025Q4",
            security_id="688981",
            title="历史季度逻辑",
            direction="观察",
            core_view="迁移时保留，不再作为维护入口",
            established_on=date(2025, 10, 20),
            owner="研究员A",
            status=ThesisStatus.VALIDATING,
            is_current=False,
            superseded_by_thesis_id=current.thesis_id,
        )
    )

    assert uow.thesis.get("THS-688981-2025Q4") is not None
    assert uow.thesis.get_by_security("688981") == current
    rows, total = uow.thesis.search(ThesisQuery())
    assert total == 1
    assert [row.thesis_id for row in rows] == [current.thesis_id]
