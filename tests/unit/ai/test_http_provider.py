from __future__ import annotations

import json

import httpx
import pytest

from app.ai.errors import ModelUnavailable
from app.ai.gateway import Gateway
from app.ai.providers.http import HttpProvider
from app.core.config import Settings
from app.core.enums import AiStatus


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "llm_provider": "http",
        "llm_endpoint": "https://model.internal/v1/chat/completions",
        "llm_api_key": "test-secret",
        "llm_model_version": "approved-model-v1",
        "llm_max_retries": 0,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _draft_response() -> dict[str, object]:
    return {
        "title": "收入增长逻辑",
        "direction": None,
        "core_view": "订单增长应支持后续收入增长",
        "hypotheses": [
            {
                "statement": "订单增长可转化为收入",
                "hypothesis_type": "经营",
                "importance": "核心",
                "metric_suggestions": [],
                "evidence_locator": None,
            },
            {
                "statement": "毛利率保持稳定",
                "hypothesis_type": "盈利",
                "importance": "辅助",
                "metric_suggestions": [],
                "evidence_locator": None,
            },
        ],
        "risks": [],
        "invalidation_suggestions": [],
        "citations": [],
        "unsupported_claims": [],
        "confidence": 0.8,
    }


def test_http_provider_calls_compatible_endpoint_and_validates_contract() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("Authorization")
        captured["request"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(_draft_response())}}]},
        )

    settings = _settings()
    provider = HttpProvider(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))
    outcome = Gateway(settings=settings, provider=provider).thesis_draft(
        security_id="600000.SH",
        view="订单增长",
        segments=[],
        source_document_id=None,
    )

    assert outcome.ai_status is AiStatus.CANDIDATE
    assert outcome.payload["model_version"] == "approved-model-v1"
    assert outcome.payload["security_id"] == "600000.SH"
    assert captured["authorization"] == "Bearer test-secret"
    assert captured["request"]["response_format"] == {"type": "json_object"}  # type: ignore[index]


def test_http_provider_marks_non_retryable_client_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, request=request)

    settings = _settings()
    provider = HttpProvider(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))

    with pytest.raises(ModelUnavailable) as raised:
        provider.draft_thesis(security_id="600000.SH", view="观点", segments=[])

    assert raised.value.retryable is False


def test_http_provider_rejects_cleartext_remote_endpoint() -> None:
    settings = _settings(llm_endpoint="http://model.internal/v1/chat/completions")

    with pytest.raises(ModelUnavailable) as raised:
        HttpProvider(settings)

    assert raised.value.retryable is False


def test_http_provider_retries_transient_status() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(_draft_response())}}]},
        )

    settings = _settings(llm_max_retries=1)
    provider = HttpProvider(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))

    provider.draft_thesis(security_id="600000.SH", view="观点", segments=[])

    assert calls == 2


def test_deepseek_flash_request_is_deterministic_and_retries_empty_json() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "id": "ds-empty",
                    "choices": [{"finish_reason": "stop", "message": {"content": ""}}],
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "ds-valid",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(_draft_response())},
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            },
        )

    settings = _settings(
        llm_endpoint="https://api.deepseek.com/chat/completions",
        llm_model_version="deepseek-v4-flash",
        llm_max_retries=1,
    )
    provider = HttpProvider(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))

    outcome = Gateway(settings=settings, provider=provider).thesis_draft(
        security_id="600000.SH", view="观点", segments=[]
    )

    assert len(requests) == 2
    assert requests[0]["model"] == "deepseek-v4-flash"
    assert requests[0]["thinking"] == {"type": "disabled"}
    assert requests[0]["temperature"] == 0
    assert requests[0]["max_tokens"] == 4096
    assert "reasoning_effort" not in requests[0]
    assert outcome.payload["model_metadata"] == {
        "provider": "deepseek",
        "request_id": "ds-valid",
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        "finish_reason": "stop",
    }


def test_deepseek_endpoint_requires_server_side_api_key() -> None:
    settings = _settings(
        llm_endpoint="https://api.deepseek.com/chat/completions",
        llm_model_version="deepseek-v4-flash",
        llm_api_key=None,
    )

    with pytest.raises(ModelUnavailable) as raised:
        HttpProvider(settings)

    assert raised.value.retryable is False


def test_deepseek_thinking_mode_omits_ineffective_temperature() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(_draft_response())}}]},
        )

    settings = _settings(
        llm_endpoint="https://api.deepseek.com/chat/completions",
        llm_model_version="deepseek-v4-flash",
        llm_thinking_mode="enabled",
        llm_reasoning_effort="high",
    )
    provider = HttpProvider(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))

    provider.draft_thesis(security_id="600000.SH", view="观点", segments=[])

    assert captured["thinking"] == {"type": "enabled"}
    assert captured["reasoning_effort"] == "high"
    assert "temperature" not in captured


def test_thesis_provider_drops_numeric_hypothesis_reference_before_validation() -> None:
    response_payload = _draft_response()
    response_payload["invalidation_suggestions"] = [
        {
            "statement": "收入连续两个季度低于阈值时重新评估",
            "hypothesis_ref": 0,
            "require_all": True,
            "consecutive_periods": 2,
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(response_payload)}}]},
        )

    settings = _settings()
    provider = HttpProvider(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))

    outcome = Gateway(settings=settings, provider=provider).thesis_draft(
        security_id="600000.SH", view="观点", segments=[]
    )

    assert outcome.ai_status is AiStatus.CANDIDATE
    assert outcome.payload["invalidation_suggestions"][0]["hypothesis_ref"] is None
