from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from app.ai.errors import ModelUnavailable
from app.ai.gateway import Gateway
from app.ai.providers.http import HttpLLMProvider, HttpProvider
from app.core.config import Settings
from app.core.enums import AiStatus


def test_openai_compatible_provider_supports_metric_contract_without_network() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["model"] == "deepseek-v4-flash"
        assert body["response_format"] == {"type": "json_object"}
        system = body["messages"][0]["content"]
        assert "JSON Schema (metric_explain)" in system
        assert '"required"' in system
        payload = {
            "summary": "程序计算结果已接收",
            "meaning": "该结果支持继续观察当前假设",
            "suggested_tracking": ["跟踪下一报告期同口径结果"],
            "confidence": 0.8,
            "ai_status": "候选",
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]},
        )

    settings = Settings(
        _env_file=None,
        llm_provider="http",
        llm_endpoint="https://api.deepseek.com",
        llm_api_key="test-key",
        llm_model_version="deepseek-v4-flash",
    )
    provider = HttpLLMProvider(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))
    outcome = Gateway(settings=settings, provider=provider).metric_explain(
        security_id="000538.SZ",
        hypothesis_id="H1",
        hypothesis="收入增长",
        calc_result={"verdict": "支持"},
    )

    assert outcome.ai_status is AiStatus.CANDIDATE
    assert outcome.payload["calculation_source"] == "app.calc"
    assert outcome.payload["model_version"] == "deepseek-v4-flash"


def test_gateway_retries_once_with_schema_errors_for_http_provider() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        payload = (
            {"summary": "missing required fields"}
            if len(requests) == 1
            else {
                "summary": "calculation result received",
                "meaning": "continue human review",
                "suggested_tracking": [],
                "confidence": 0.8,
            }
        )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(payload)}}]},
        )

    settings = Settings(
        _env_file=None,
        llm_provider="http",
        llm_endpoint="https://api.deepseek.com",
        llm_api_key="test-key",
        llm_max_retries=0,
    )
    outcome = Gateway(
        settings=settings,
        provider=HttpProvider(
            settings, client=httpx.Client(transport=httpx.MockTransport(handler))
        ),
    ).metric_explain(
        security_id="000538.SZ",
        hypothesis_id="H1",
        hypothesis="revenue growth",
        calc_result={"verdict": "support"},
    )

    assert outcome.usable
    assert outcome.repaired
    assert len(requests) == 2
    assert "上一次输出未通过契约或证据校验" in requests[1]["messages"][1]["content"]


def test_http_provider_accepts_full_endpoint_and_secret_str() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["authorization"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary": "已接收程序结果",
                                    "meaning": "继续人工判断",
                                    "suggested_tracking": [],
                                    "confidence": 0.8,
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )

    settings = SimpleNamespace(
        llm_endpoint="https://model.internal/v1/chat/completions",
        llm_api_key=SecretStr("server-secret"),
        llm_model_version="approved-model-v1",
        llm_timeout_seconds=30.0,
        llm_max_retries=0,
    )
    provider = HttpProvider(  # type: ignore[arg-type]
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    provider.explain_metric(
        security_id="000538.SZ",
        hypothesis_id="H1",
        hypothesis="收入增长",
        calc_result={"verdict": "支持"},
    )

    assert captured == {
        "path": "/v1/chat/completions",
        "authorization": "Bearer server-secret",
    }


def test_gateway_propagates_retryable_provider_outage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    settings = Settings(
        _env_file=None,
        llm_provider="http",
        llm_endpoint="https://model.internal/v1/chat/completions",
        llm_max_retries=0,
    )
    gateway = Gateway(
        settings=settings,
        provider=HttpProvider(
            settings,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        ),
    )

    with pytest.raises(ModelUnavailable) as raised:
        gateway.thesis_draft(
            security_id="000538.SZ",
            view="订单增长",
            segments=[],
        )

    assert raised.value.retryable is True


def test_invalid_model_json_degrades_through_schema_validation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={"choices": [{"message": {"content": "not-json"}}]},
        )

    settings = Settings(
        _env_file=None,
        llm_provider="http",
        llm_endpoint="https://model.internal/v1/chat/completions",
        llm_max_retries=0,
    )
    outcome = Gateway(
        settings=settings,
        provider=HttpProvider(
            settings,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        ),
    ).thesis_draft(
        security_id="000538.SZ",
        view="订单增长",
        segments=[],
    )

    assert outcome.ai_status is AiStatus.PARSE_FAILED
    assert outcome.errors
