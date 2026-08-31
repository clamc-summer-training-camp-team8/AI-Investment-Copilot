"""数据库账号认证、密码摘要和短期访问令牌。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import Settings
from app.db.models.governance import AuditLog, UserAccount
from app.db.session import session_scope

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
_USER_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class PasswordChangeFailed(ValueError):
    """当前密码或新密码不满足要求。"""


@dataclass(frozen=True)
class UserIdentity:
    user_id: str
    teams: tuple[str, ...]
    document_labels: tuple[str, ...]
    is_admin: bool
    must_change_password: bool


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("密码不能为空")
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, raw_n, raw_r, raw_p, raw_salt, raw_digest = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        n, r, p = int(raw_n), int(raw_r), int(raw_p)
        if n > 2**16 or r > 16 or p > 4:
            return False
        expected = _unb64(raw_digest)
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=_unb64(raw_salt), n=n, r=r, p=p, dklen=len(expected)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _identity(account: UserAccount) -> UserIdentity:
    return UserIdentity(
        user_id=account.user_id,
        teams=tuple(str(item) for item in account.teams),
        document_labels=tuple(str(item) for item in account.document_labels),
        is_admin=account.is_admin,
        must_change_password=account.must_change_password,
    )


def authenticate_user(user_id: str, password: str) -> UserIdentity | None:
    with session_scope() as session:
        account = session.get(UserAccount, user_id.strip())
        if (
            account is None
            or not account.active
            or not verify_password(password, account.password_hash)
        ):
            return None
        session.add(
            AuditLog(
                actor=account.user_id,
                action="login",
                object_type="user_account",
                object_id=account.user_id,
                detail={"result": "success"},
            )
        )
        return _identity(account)


def get_user_identity(user_id: str) -> UserIdentity | None:
    with session_scope() as session:
        account = session.get(UserAccount, user_id)
        if account is None or not account.active:
            return None
        return _identity(account)


def validate_new_password(new_password: str, *, user_id: str) -> None:
    if len(new_password) < 10:
        raise PasswordChangeFailed("新密码至少需要 10 个字符")
    if user_id.casefold() in new_password.casefold():
        raise PasswordChangeFailed("新密码不能包含账号名")
    if new_password in {"12345678", "1234567890", "password", "Password123"}:
        raise PasswordChangeFailed("新密码过于常见，请使用更强的密码")


def change_password(user_id: str, current_password: str, new_password: str) -> UserIdentity:
    validate_new_password(new_password, user_id=user_id)
    with session_scope() as session:
        account = session.get(UserAccount, user_id)
        if (
            account is None
            or not account.active
            or not verify_password(current_password, account.password_hash)
        ):
            raise PasswordChangeFailed("当前密码不正确")
        if verify_password(new_password, account.password_hash):
            raise PasswordChangeFailed("新密码不能与当前密码相同")
        account.password_hash = hash_password(new_password)
        account.must_change_password = False
        account.password_changed_at = datetime.now(UTC)
        session.add(
            AuditLog(
                actor=account.user_id,
                action="change_password",
                object_type="user_account",
                object_id=account.user_id,
                detail={"result": "success"},
            )
        )
        return _identity(account)


def upsert_user(
    *,
    user_id: str,
    password: str,
    teams: list[str],
    document_labels: list[str] | None = None,
    is_admin: bool = False,
    must_change_password: bool = True,
) -> UserIdentity:
    user_id = user_id.strip()
    if not _USER_ID.fullmatch(user_id):
        raise ValueError("账号只能包含字母、数字、点、下划线和连字符，最长 64 位")
    if not password:
        raise ValueError("密码不能为空")
    labels = document_labels or ["公开", "内部"]
    normalized_teams = sorted({item.strip() for item in teams if item.strip()})
    with session_scope() as session:
        account = session.get(UserAccount, user_id)
        created = account is None
        if account is None:
            account = UserAccount(
                user_id=user_id,
                password_hash=hash_password(password),
                teams=normalized_teams,
                document_labels=labels,
                is_admin=is_admin,
                active=True,
                must_change_password=must_change_password,
            )
            session.add(account)
        else:
            account.password_hash = hash_password(password)
            account.teams = normalized_teams
            account.document_labels = labels
            account.is_admin = is_admin
            account.active = True
            account.must_change_password = must_change_password
            account.password_changed_at = None
        session.add(
            AuditLog(
                actor="system-admin",
                action="create_user" if created else "reset_user",
                object_type="user_account",
                object_id=user_id,
                detail={"teams": normalized_teams, "must_change_password": must_change_password},
            )
        )
        return _identity(account)


def issue_access_token(identity: UserIdentity, settings: Settings) -> tuple[str, int]:
    configured = settings.auth_jwt_secret
    if configured is None or len(configured.get_secret_value().encode()) < 32:
        raise RuntimeError("AUTH_JWT_SECRET 至少需要 32 字节")
    now = datetime.now(UTC)
    expires_in = settings.auth_access_token_minutes * 60
    token = jwt.encode(
        {
            "sub": identity.user_id,
            "teams": list(identity.teams),
            "document_labels": list(identity.document_labels),
            "is_admin": identity.is_admin,
            "must_change_password": identity.must_change_password,
            "iat": now,
            "exp": now + timedelta(seconds=expires_in),
            "iss": settings.auth_jwt_issuer,
            "aud": settings.auth_jwt_audience,
        },
        configured.get_secret_value(),
        algorithm=settings.auth_jwt_algorithm,
    )
    return token, expires_in
