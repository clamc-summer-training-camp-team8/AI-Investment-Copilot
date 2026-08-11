from __future__ import annotations

from typing import Any

import pytest

from analytics.evaluation.run_nine_company_model import (
    EvaluationCase,
    build_artifact,
    evaluate_cases,
    load_cases,
    summarize,
    validate_deepseek_chat_config,
)
from app.ai.contracts.validator import ValidationOutcome
from app.ai.errors import ModelUnavailable
from app.core.config import Settings
from app.core.enums import AiStatus


class FakeGateway:
    def event_impact(self, **kwargs: Any) -> ValidationOutcome:
        return ValidationOutcome(
            ai_status=AiStatus.CANDIDATE,
            payload={
                "relevance": "相关",
                "event": {"evidence_locator": kwargs["segment_locator"]},
                "signal": {"impact_direction": "支持", "confidence": 0.88},
                "model_version": "deepseek-v4-flash",
                "prompt_version": "event-impact-v2-mentor-ruling",
                "model_metadata": {
                    "request_id": "request-1",
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                },
            },
        )


def _case(gold_direction: str = "支持") -> EvaluationCase:
    return EvaluationCase(
        case_id="case-1",
        industry="行业",
        company_name="公司",
        security_id="000001.SZ",
        thesis_title="收入底盘",
        thesis_statement="收入不低于阈值",
        metric_name="收入",
        metric_unit="元",
        threshold="100",
        period="2024Q2",
        period_end="2024-06-30",
        disclosed_at="2024-08-01",
        actual_value="120",
        source_document_id="DOC-1",
        evidence="第二季度收入为120元。",
        gold_direction=gold_direction,
    )


def test_frozen_dataset_has_27_researcher_gold_events() -> None:
    cases = load_cases()

    assert len(cases) == 27
    assert {case.industry for case in cases} == {"芯片半导体", "医药", "新能源汽车"}
    assert all(case.gold_direction in {"支持", "冲突", "中性", "无关"} for case in cases)


def test_evaluator_records_direction_citation_latency_and_usage() -> None:
    results = evaluate_cases(FakeGateway(), [_case()])
    metrics = summarize(results, expected_count=1)

    assert results[0].exact_match is True
    assert results[0].citation_locator_valid is True
    assert results[0].request_id == "request-1"
    assert metrics["direction_accuracy"] == 1.0
    assert metrics["citation_locator_integrity"] == 1.0
    assert metrics["usage_totals"] == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }


def test_artifact_never_contains_api_key_or_raw_prompt() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="http",
        llm_endpoint="https://api.deepseek.com/chat/completions",
        llm_api_key="do-not-persist",
        llm_model_version="deepseek-v4-flash",
    )
    case = _case()
    artifact = build_artifact(settings, [case], evaluate_cases(FakeGateway(), [case]))
    rendered = str(artifact)

    assert "do-not-persist" not in rendered
    assert artifact["prompt_or_raw_response_persisted"] is False


def test_live_evaluation_requires_server_side_api_key() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="http",
        llm_endpoint="https://api.deepseek.com/chat/completions",
        llm_model_version="deepseek-v4-flash",
        llm_api_key=None,
    )

    with pytest.raises(ModelUnavailable, match="LLM_API_KEY"):
        validate_deepseek_chat_config(settings)
