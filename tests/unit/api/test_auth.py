from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import HTTPException

from app.api.auth import AuthenticationFailed, verify_bearer_token
from app.api.deps import get_actor
from app.api.routers.authentication import auth_config
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


def test_forced_password_change_token_cannot_access_product_api() -> None:
    token = _token(must_change_password=True)

    with pytest.raises(AuthenticationFailed, match="必须先修改初始密码"):
        verify_bearer_token(token, _settings())

    actor = verify_bearer_token(token, _settings(), allow_password_change_required=True)
    assert actor.user_id == "researcher-1"


def test_trusted_proxy_returns_gateway_actor() -> None:
    conf = Settings(
        _env_file=None,
        env="integration",
        auth_mode="trusted_proxy",
        auth_trusted_proxy_secret=SECRET,
    )

    actor = get_actor(conf, None, "researcher-1", "team-a,team-b", SECRET)

    assert actor.user_id == "researcher-1"
    assert actor.teams == frozenset({"team-a", "team-b"})


def test_trusted_proxy_rejects_forged_identity_headers() -> None:
    conf = Settings(
        _env_file=None,
        env="integration",
        auth_mode="trusted_proxy",
        auth_trusted_proxy_secret=SECRET,
    )

    with pytest.raises(HTTPException) as caught:
        get_actor(conf, None, "forged-user", "team-a", "wrong-proxy-secret")

    assert caught.value.status_code == 401


def test_non_local_plain_trusted_headers_remain_disabled() -> None:
    conf = Settings(_env_file=None, env="integration", auth_mode="trusted_headers")

    with pytest.raises(HTTPException) as caught:
        get_actor(conf, None, "forged-user", "team-a", None)

    assert caught.value.status_code == 503


def test_auth_config_exposes_independent_research_feature_flags() -> None:
    result = auth_config(
        Settings(
            _env_file=None,
            global_search_enabled=True,
            knowledge_qa_enabled=False,
        )
    )

    assert result.global_search_enabled is True
    assert result.knowledge_qa_enabled is False
    assert result.quant_research_enabled is True
    assert result.quant_demo_enabled is False
