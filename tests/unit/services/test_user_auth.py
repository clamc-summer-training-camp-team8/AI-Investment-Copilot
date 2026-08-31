from __future__ import annotations

import jwt
import pytest

from app.core.config import Settings
from app.services.user_auth import (
    PasswordChangeFailed,
    UserIdentity,
    hash_password,
    issue_access_token,
    validate_new_password,
    verify_password,
)


def test_password_hash_uses_random_salt_and_verifies() -> None:
    first = hash_password("12345678")
    second = hash_password("12345678")

    assert first != second
    assert verify_password("12345678", first)
    assert not verify_password("wrong", first)


def test_new_password_policy_rejects_common_password_and_user_id() -> None:
    with pytest.raises(PasswordChangeFailed):
        validate_new_password("1234567890", user_id="liaojun")
    with pytest.raises(PasswordChangeFailed):
        validate_new_password("liaojun-2026-strong", user_id="liaojun")


def test_access_token_contains_forced_change_claim() -> None:
    settings = Settings(
        _env_file=None,
        auth_mode="jwt",
        auth_jwt_secret="a-secure-test-secret-with-at-least-32-bytes",
        auth_jwt_issuer="issuer",
        auth_jwt_audience="audience",
        auth_access_token_minutes=10,
    )
    identity = UserIdentity(
        user_id="liaojun",
        teams=("research",),
        document_labels=("公开", "内部"),
        is_admin=False,
        must_change_password=True,
    )

    token, expires_in = issue_access_token(identity, settings)
    claims = jwt.decode(
        token,
        settings.auth_jwt_secret.get_secret_value(),
        algorithms=["HS256"],
        audience="audience",
        issuer="issuer",
    )

    assert expires_in == 600
    assert claims["must_change_password"] is True
