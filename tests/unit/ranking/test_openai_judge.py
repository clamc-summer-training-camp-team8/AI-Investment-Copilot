from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import Settings
from app.ranking.judge import RankingJudgeUnavailable
from app.ranking.openai_judge import OpenAIRankingJudge


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "ranking_judge_enabled": True,
        "llm_api_key": "test-secret",
        "llm_max_retries": 0,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_openai_judge_uses_responses_structured_output() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        output = {
            "ranking": [
                {
                    "object_id": "segment-1",
                    "rank": 1,
                    "score": 0.9,
                    "confidence": 0.8,
                    "reason_codes": ["METRIC_VERIFIABLE"],
                    "citation_locators": ["segment-1"],
                }
            ]
        }
        return httpx.Response(
            200,
            json={"output": [{"content": [{"type": "output_text", "text": json.dumps(output)}]}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    rows = OpenAIRankingJudge(_settings(), client=client).judge(
        [{"object_id": "segment-1", "content": "销量增长"}]
    )

    assert rows[0].score == 0.9
    assert captured["authorization"] == "Bearer test-secret"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "gpt-5.6-terra"
    assert body["store"] is False
    assert body["text"]["format"]["type"] == "json_schema"


def test_openai_judge_requires_explicit_enablement_and_key() -> None:
    with pytest.raises(RankingJudgeUnavailable):
        OpenAIRankingJudge(_settings(ranking_judge_enabled=False))
    with pytest.raises(RankingJudgeUnavailable):
        OpenAIRankingJudge(_settings(llm_api_key=None))
