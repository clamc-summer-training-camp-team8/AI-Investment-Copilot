"""产品内登录、当前会话和首次改密端点。"""

from __future__ import annotations

from collections import defaultdict, deque
from threading import Lock
from time import monotonic

from fastapi import APIRouter, HTTPException, Request, Response

from app.api.deps import SessionActorDep, SettingsDep
from app.schemas.auth import (
    AuthConfigOut,
    AuthSessionOut,
    AuthUserOut,
    ChangePasswordIn,
    LoginIn,
)
from app.services import user_auth

router = APIRouter(prefix="/auth", tags=["authentication"])

_WINDOW_SECONDS = 10 * 60
_MAX_FAILURES = 5
_failed_logins: dict[str, deque[float]] = defaultdict(deque)
_failed_logins_lock = Lock()


def _rate_key(request: Request, user_id: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{host}:{user_id.casefold()}"


def _is_rate_limited(key: str) -> bool:
    cutoff = monotonic() - _WINDOW_SECONDS
    with _failed_logins_lock:
        attempts = _failed_logins[key]
        while attempts and attempts[0] < cutoff:
            attempts.popleft()
        return len(attempts) >= _MAX_FAILURES


def _record_failure(key: str) -> None:
    with _failed_logins_lock:
        _failed_logins[key].append(monotonic())


def _clear_failures(key: str) -> None:
    with _failed_logins_lock:
        _failed_logins.pop(key, None)


def _user_out(identity: user_auth.UserIdentity) -> AuthUserOut:
    return AuthUserOut(
        user_id=identity.user_id,
        teams=list(identity.teams),
        must_change_password=identity.must_change_password,
    )


def _session_out(identity: user_auth.UserIdentity, settings: SettingsDep) -> AuthSessionOut:
    token, expires_in = user_auth.issue_access_token(identity, settings)
    return AuthSessionOut(access_token=token, expires_in=expires_in, user=_user_out(identity))


@router.get("/config", response_model=AuthConfigOut)
def auth_config(settings: SettingsDep) -> AuthConfigOut:
    return AuthConfigOut(
        login_required=settings.auth_mode == "jwt",
        password_change_supported=settings.auth_mode == "jwt",
    )


@router.post("/login", response_model=AuthSessionOut)
def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    settings: SettingsDep,
) -> AuthSessionOut:
    if settings.auth_mode != "jwt":
        raise HTTPException(status_code=409, detail="当前环境不使用产品内登录")
    key = _rate_key(request, payload.user_id)
    if _is_rate_limited(key):
        raise HTTPException(status_code=429, detail="登录失败次数过多，请 10 分钟后再试")
    identity = user_auth.authenticate_user(payload.user_id, payload.password)
    if identity is None:
        _record_failure(key)
        raise HTTPException(status_code=401, detail="账号或密码不正确")
    _clear_failures(key)
    response.headers["Cache-Control"] = "no-store"
    return _session_out(identity, settings)


@router.get("/me", response_model=AuthUserOut)
def current_user(actor: SessionActorDep, settings: SettingsDep) -> AuthUserOut:
    if settings.auth_mode != "jwt":
        return AuthUserOut(
            user_id=actor.user_id,
            teams=sorted(actor.teams),
            must_change_password=False,
        )
    identity = user_auth.get_user_identity(actor.user_id)
    if identity is None:
        raise HTTPException(status_code=401, detail="账号已停用或不存在")
    return _user_out(identity)


@router.post("/change-password", response_model=AuthSessionOut)
def change_password(
    payload: ChangePasswordIn,
    actor: SessionActorDep,
    response: Response,
    settings: SettingsDep,
) -> AuthSessionOut:
    if settings.auth_mode != "jwt":
        raise HTTPException(status_code=409, detail="当前环境不支持产品内改密")
    try:
        identity = user_auth.change_password(
            actor.user_id,
            payload.current_password,
            payload.new_password,
        )
    except user_auth.PasswordChangeFailed as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response.headers["Cache-Control"] = "no-store"
    return _session_out(identity, settings)
