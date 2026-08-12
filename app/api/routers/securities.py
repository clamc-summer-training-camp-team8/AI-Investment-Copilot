"""证券主数据查询与建档路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import ActorDep, UowDep
from app.schemas.security import SecurityIn, SecurityOut
from app.services import security as security_service
from app.services.errors import ValidationFailed
from app.services.permission import Actor

router = APIRouter(prefix="/securities", tags=["securities"])


def _out(record) -> SecurityOut:
    return SecurityOut(
        security_id=record.security_id,
        name=record.name,
        ticker=record.ticker,
        industry=record.industry,
        aliases=record.aliases,
    )


def _require_local_admin(actor: Actor) -> None:
    # MVP 尚无独立 RBAC 表；本地代理固定注入这个账号。生产上线
    # 前应替换为组织目录中的 security_master:write 权限。
    if actor.user_id != "analyst-mvp" and "security-admin" not in actor.teams:
        raise HTTPException(status_code=403, detail="当前账户无证券主数据建档权限")


@router.get("", response_model=list[SecurityOut])
def list_securities(
    actor: ActorDep,
    uow: UowDep,
    keyword: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[SecurityOut]:
    del actor
    return [_out(record) for record in uow.securities.search(keyword, limit=limit)]


@router.post("", response_model=SecurityOut, status_code=201)
def create_security(payload: SecurityIn, actor: ActorDep, uow: UowDep) -> SecurityOut:
    _require_local_admin(actor)
    try:
        record = security_service.create(
            uow,
            security_id=payload.security_id,
            name=payload.name,
            ticker=payload.ticker,
            industry=payload.industry,
            aliases=payload.aliases,
            actor=actor,
        )
    except ValidationFailed as exc:
        status_code = 409 if "已建档" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return _out(record)
