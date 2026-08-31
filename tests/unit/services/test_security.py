from __future__ import annotations

import pytest

from app.services import security
from app.services.errors import ValidationFailed
from app.services.permission import Actor
from tests.fakes import build_fake_uow


def test_create_and_require_security_normalizes_identifier() -> None:
    uow = build_fake_uow()
    actor = Actor(user_id="researcher-1")

    created = security.create(
        uow,
        security_id="abc-001.sh",
        name="新公司",
        ticker=None,
        industry="高端制造",
        aliases=["新公司", "新公司"],
        actor=actor,
    )

    assert created.security_id == "ABC-001.SH"
    assert security.require(uow, "abc-001.sh").name == "新公司"
    assert created.aliases == ["新公司"]
    assert "新建证券主数据" in uow.audit.actions()  # type: ignore[attr-defined]


def test_duplicate_security_is_rejected() -> None:
    uow = build_fake_uow()
    actor = Actor(user_id="researcher-1")
    kwargs = {
        "security_id": "600000.SH",
        "name": "测试公司",
        "ticker": None,
        "industry": None,
        "aliases": None,
        "actor": actor,
    }
    security.create(uow, **kwargs)

    with pytest.raises(ValidationFailed, match="已建档"):
        security.create(uow, **kwargs)
