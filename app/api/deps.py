"""依赖注入。

`app/api` 不允许 import `app/db`（`.importlinter` 强制），所以这里通过
`app.db.repositories.build_uow` 拿不到 UnitOfWork——那会破坏分层。做法是让
api 只依赖 `app.services` 暴露的工厂，由服务层去组装仓储。

这层刻意保持薄：解析请求、取身份、调一个 service、组装响应。
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException

from app.core.config import Settings, settings
from app.services.permission import Actor
from app.services.ports import UnitOfWork
from app.services.uow import uow_scope


def get_settings() -> Settings:
    return settings


def get_actor(
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
    x_user_teams: Annotated[str | None, Header(alias="X-User-Teams")] = None,
) -> Actor:
    """从请求头取身份。

    MVP 用请求头承载身份，前提是**服务只暴露在内网网关之后**，由网关校验并注入
    这两个头。直接暴露到公网等于任何人都能声明任意身份——上线前必须换成校验过的
    令牌。这条限制写在这里，不是留给以后再想的事。
    """
    if not x_user_id:
        raise HTTPException(status_code=401, detail="缺少身份信息")
    teams = frozenset(t.strip() for t in (x_user_teams or "").split(",") if t.strip())
    return Actor(user_id=x_user_id, teams=teams)


def get_uow() -> Iterator[UnitOfWork]:
    """每个请求一个事务。异常回滚，正常提交。"""
    with uow_scope() as uow:
        yield uow


ActorDep = Annotated[Actor, Depends(get_actor)]
UowDep = Annotated[UnitOfWork, Depends(get_uow)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
