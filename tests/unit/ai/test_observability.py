from __future__ import annotations

from decimal import Decimal

from app.ai.observability import usage_from_payload
from app.core.config import Settings


def test_usage_normalizes_tokens_latency_and_cost() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="http",
        llm_endpoint="https://example.com",
        llm_input_cost_per_million=Decimal("2"),
        llm_output_cost_per_million=Decimal("8"),
    )
    usage = usage_from_payload(
        {
            "model_version": "model-v1",
            "prompt_version": "prompt-v1",
            "model_metadata": {
                "provider": "deepseek",
                "request_id": "req-1",
                "latency_ms": 123,
                "attempt_count": 2,
                "usage": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 500,
                    "total_tokens": 1500,
                },
            },
        },
        settings,
    )

    assert usage.input_tokens == 1000
    assert usage.output_tokens == 500
    assert usage.total_tokens == 1500
    assert usage.latency_ms == 123
    assert usage.attempt_count == 2
    assert usage.cost_amount == Decimal("0.00600000")
