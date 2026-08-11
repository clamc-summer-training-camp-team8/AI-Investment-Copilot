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

from app.api.auth import AuthenticationFailed, verify_bearer_token
from app.core.config import Settings, settings
from app.services.permission import Actor
from app.services.ports import UnitOfWork
from app.services.uow import uow_scope


def get_settings() -> Settings:
    return settings


def get_actor(
    conf: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
    x_user_teams: Annotated[str | None, Header(alias="X-User-Teams")] = None,
) -> Actor:
    """从请求头取身份。

    MVP 用请求头承载身份，前提是**服务只暴露在内网网关之后**，由网关校验并注入
    这两个头。直接暴露到公网等于任何人都能声明任意身份——上线前必须换成校验过的
    令牌。这条限制写在这里，不是留给以后再想的事。

    **用户标识必须是 ASCII。** HTTP 头按 RFC 7230 只能承载 latin-1，而本项目
    示例数据里的负责人是「研究员A」这类中文名。中文直接放进 X-User-Id，客户端在
    编码阶段就会失败（不是服务端返回错误，是请求根本发不出去）。因此网关注入的
    应当是账号 ID 或工号，中文姓名走展示层查询，不进请求头。
    """
    if conf.auth_mode == "trusted_headers":
        if conf.env != "local":
            raise HTTPException(status_code=503, detail="非本地环境必须启用 AUTH_MODE=jwt")
        if not x_user_id:
            raise HTTPException(status_code=401, detail="缺少身份信息")
        teams = frozenset(t.strip() for t in (x_user_teams or "").split(",") if t.strip())
        return Actor(user_id=x_user_id, teams=teams)

    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=401,
            detail="缺少 Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return verify_bearer_token(token, conf)
    except AuthenticationFailed as exc:
        raise HTTPException(
            status_code=401,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_uow() -> Iterator[UnitOfWork]:
    """每个请求一个事务。异常回滚，正常提交。"""
    with uow_scope() as uow:
        yield uow


ActorDep = Annotated[Actor, Depends(get_actor)]
UowDep = Annotated[UnitOfWork, Depends(get_uow)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
