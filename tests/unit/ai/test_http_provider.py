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


def _batch_impact_response() -> dict[str, object]:
    def impact(hypothesis_id: str, direction: str, relevance: str) -> dict[str, object]:
        return {
            "thesis_id": "THS-001",
            "hypothesis_id": hypothesis_id,
            "relevance": relevance,
            "inference": f"事件对 {hypothesis_id} 的候选影响",
            "citations": ["DOC-001#paragraph-1"],
            "unsupported_claims": [],
            "signal": {
                "direction": "中性",
                "impact_direction": direction,
                "strength": 0.7,
                "confidence": 0.8,
                "horizon": "中期",
                "rationale": f"{hypothesis_id} 批量判断",
                "transmission_path": "事件 → 业务变量 → 目标假设",
                "suggested_tracking": [],
                "requires_human_review": True,
            },
        }

    return {
        "event": {"fact": "公司披露经营指标变化"},
        "impacts": [
            impact("H1", "冲突", "相关"),
            impact("H2", "无关", "不相关"),
        ],
    }


def test_http_event_impact_sends_all_candidates_in_one_model_call() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(_batch_impact_response())}}]},
        )

    settings = _settings()
    gateway = Gateway(
        settings=settings,
        provider=HttpProvider(
            settings, client=httpx.Client(transport=httpx.MockTransport(handler))
        ),
    )
    outcome = gateway.event_impact(
        document_id="DOC-001",
        security_id="600000.SH",
        segment_locator="DOC-001#paragraph-1",
        segment_text="公司披露经营指标变化",
        disclosure_time="2026-08-10T09:00:00+08:00",
        candidates=[
            {"thesis_id": "THS-001", "hypothesis_id": "H1", "statement": "毛利率改善"},
            {
                "thesis_id": "THS-001",
                "hypothesis_id": "H2",
                "statement": "资本开支增长",
            },
        ],
        evidence_contexts=[
            {
                "hypothesis_id": "H1",
                "evidence": [
                    {
                        "context_type": "current_event_evidence",
                        "locator": "DOC-001#paragraph-1",
                        "content": "公司披露经营指标变化",
                    }
                ],
            }
        ],
        event_type="业绩",
    )

    assert outcome.usable
    assert len(requests) == 1
    prompt = requests[0]["messages"][1]["content"]  # type: ignore[index]
    assert "H1" in prompt and "H2" in prompt
    assert "current_event_evidence" in prompt
    assert [item["hypothesis_id"] for item in outcome.payload["impacts"]] == [
        "H1",
        "H2",
    ]
    assert outcome.payload["impacts"][1]["signal"]["impact_direction"] == "无关"


def test_http_batch_impact_prompt_requires_nested_event_impact_shape() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "results": [
                                        {
                                            "event_id": "EVT-001",
                                            "analysis": _batch_impact_response(),
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        )

    settings = _settings()
    gateway = Gateway(
        settings=settings,
        provider=HttpProvider(
            settings, client=httpx.Client(transport=httpx.MockTransport(handler))
        ),
    )
    outcomes = gateway.event_impacts(
        document_id="DOC-001",
        security_id="600000.SH",
        events=[
            {
                "event_id": "EVT-001",
                "segment_locator": "DOC-001#paragraph-1",
                "segment_text": "公司披露经营指标变化",
                "disclosure_time": "2026-08-10T09:00:00+08:00",
                "event_type": "业绩",
                "candidates": [
                    {"thesis_id": "THS-001", "hypothesis_id": "H1", "statement": "毛利率改善"},
                    {"thesis_id": "THS-001", "hypothesis_id": "H2", "statement": "资本开支增长"},
                ],
                "evidence_contexts": [],
            }
        ],
    )

    prompt = captured["messages"][1]["content"]  # type: ignore[index]
    assert "analysis.impacts[i].signal" in prompt
    assert outcomes[0].usable
    assert len(outcomes[0].payload["impacts"]) == 2


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
        "latency_ms": outcome.payload["model_metadata"]["latency_ms"],
        "attempt_count": 2,
    }
    assert outcome.payload["model_metadata"]["latency_ms"] >= 0


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
