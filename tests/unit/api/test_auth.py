from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.api.auth import AuthenticationFailed, verify_bearer_token
from app.core.config import Settings

SECRET = "a-secure-test-secret-with-at-least-32-bytes"


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        auth_mode="jwt",
        auth_jwt_secret=SECRET,
        auth_jwt_issuer="issuer",
        auth_jwt_audience="audience",
    )


def _token(**overrides: object) -> str:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "sub": "researcher-1",
        "teams": ["team-a"],
        "iat": now,
        "exp": now + timedelta(minutes=10),
        "iss": "issuer",
        "aud": "audience",
    }
    claims.update(overrides)
    return jwt.encode(claims, SECRET, algorithm="HS256")


def test_verify_bearer_token_returns_actor() -> None:
    actor = verify_bearer_token(_token(), _settings())

    assert actor.user_id == "researcher-1"
    assert actor.teams == frozenset({"team-a"})


def test_verify_bearer_token_rejects_expired_token() -> None:
    with pytest.raises(AuthenticationFailed):
        verify_bearer_token(
            _token(exp=datetime.now(UTC) - timedelta(minutes=1)),
            _settings(),
        )


def test_verify_bearer_token_rejects_wrong_audience() -> None:
    with pytest.raises(AuthenticationFailed):
        verify_bearer_token(_token(aud="another-api"), _settings())
