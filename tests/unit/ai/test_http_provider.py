from __future__ import annotations

import json

import httpx

from app.ai.gateway import Gateway
from app.ai.providers.http import HttpLLMProvider
from app.core.config import Settings
from app.core.enums import AiStatus


def test_openai_compatible_provider_supports_metric_contract_without_network() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["model"] == "deepseek-v4-flash"
        assert body["response_format"] == {"type": "json_object"}
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
