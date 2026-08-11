"""Bearer JWT verification for API requests."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import jwt

from app.core.config import Settings
from app.services.permission import Actor


class AuthenticationFailed(ValueError):
    """The request did not carry a valid authenticated identity."""


def verify_bearer_token(token: str, settings: Settings) -> Actor:
    if settings.auth_jwt_secret is None:
        raise AuthenticationFailed("服务端未配置 AUTH_JWT_SECRET")
    secret = settings.auth_jwt_secret.get_secret_value()
    if len(secret.encode()) < 32:
        raise AuthenticationFailed("AUTH_JWT_SECRET 至少需要 32 字节")
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            secret,
            algorithms=[settings.auth_jwt_algorithm],
            audience=settings.auth_jwt_audience,
            issuer=settings.auth_jwt_issuer,
            leeway=settings.auth_jwt_leeway_seconds,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise AuthenticationFailed("Bearer token 无效或已过期") from exc

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise AuthenticationFailed("Bearer token 缺少有效 sub")
    raw_teams = claims.get("teams", [])
    if isinstance(raw_teams, str):
        teams: Sequence[str] = [raw_teams]
    elif isinstance(raw_teams, list) and all(isinstance(item, str) for item in raw_teams):
        teams = raw_teams
    else:
        raise AuthenticationFailed("Bearer token 的 teams 必须是字符串数组")
    return Actor(user_id=subject.strip(), teams=frozenset(item.strip() for item in teams if item))
