"""证券主数据建档服务。"""

from __future__ import annotations

import re

from app.core.domain import SecurityRecord, UnitOfWork
from app.services import audit
from app.services.errors import ValidationFailed
from app.services.permission import Actor

_SECURITY_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def create(
    uow: UnitOfWork,
    *,
    security_id: str,
    name: str,
    ticker: str | None,
    industry: str | None,
    aliases: list[str] | None,
    actor: Actor,
) -> SecurityRecord:
    normalized_id = security_id.strip().upper()
    normalized_name = name.strip()
    if not _SECURITY_ID.fullmatch(normalized_id):
        raise ValidationFailed("证券标识只能包含英文、数字、点、下划线或连字符，最长 64 位")
    if not normalized_name:
        raise ValidationFailed("证券名称不能为空")
    if uow.securities.get(normalized_id) is not None:
        raise ValidationFailed(f"证券 {normalized_id} 已建档")

    record = SecurityRecord(
        security_id=normalized_id,
        name=normalized_name,
        ticker=(ticker or normalized_id).strip().upper() or None,
        industry=(industry or "").strip() or None,
        aliases=sorted({item.strip() for item in (aliases or []) if item.strip()}),
    )
    uow.securities.add(record)
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action="新建证券主数据",
        object_type="security",
        object_id=record.security_id,
        detail={"name": record.name, "ticker": record.ticker, "industry": record.industry},
    )
    return record


def require(uow: UnitOfWork, security_id: str) -> SecurityRecord:
    record = uow.securities.get(security_id.strip().upper())
    if record is None:
        raise ValidationFailed(f"证券 {security_id} 尚未建档")
    return record
