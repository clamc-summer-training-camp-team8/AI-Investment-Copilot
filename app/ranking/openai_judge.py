"""OpenAI Responses API adapter for offline ranking-prior review."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.config import Settings
from app.ranking.judge import Judgement, RankingJudgeUnavailable


class OpenAIRankingJudge:
    def __init__(self, settings: Settings, *, client: httpx.Client | None = None) -> None:
        if not settings.ranking_judge_enabled:
            raise RankingJudgeUnavailable("排序检查员未启用")
        if settings.llm_api_key is None:
            raise RankingJudgeUnavailable("排序检查员需要服务端 LLM_API_KEY")
        self._settings = settings
        self._api_key = settings.llm_api_key.get_secret_value()
        self._client = client or httpx.Client(timeout=settings.llm_timeout_seconds)

    def judge(self, candidates: list[dict[str, object]]) -> list[Judgement]:
        schema = {
            "type": "object",
            "properties": {
                "ranking": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "object_id": {"type": "string"},
                            "rank": {"type": "integer", "minimum": 1},
                            "score": {"type": "number", "minimum": 0, "maximum": 1},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "reason_codes": {"type": "array", "items": {"type": "string"}},
                            "citation_locators": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": [
                            "object_id",
                            "rank",
                            "score",
                            "confidence",
                            "reason_codes",
                            "citation_locators",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["ranking"],
            "additionalProperties": False,
        }
        response = self._client.post(
            self._settings.ranking_judge_endpoint,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self._settings.ranking_judge_model_version,
                "store": False,
                "reasoning": {"effort": "medium"},
                "instructions": (
                    "你是权益投研知识库的排序检查员。只评价给定候选，不补充外部事实。"
                    "核心经营证据、可量化指标和重要反证优先；会议通知、法律意见书、"
                    "制度公告和重复材料降权。不得仅因观点方向相反而删除反证。"
                ),
                "input": json.dumps(candidates, ensure_ascii=False),
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "ranking_judgement",
                        "strict": True,
                        "schema": schema,
                    }
                },
                "max_output_tokens": self._settings.llm_max_output_tokens,
            },
        )
        if response.is_error:
            raise RankingJudgeUnavailable(f"OpenAI 排序检查失败: HTTP {response.status_code}")
        try:
            body: dict[str, Any] = response.json()
            output_text = body.get("output_text") or _response_output_text(body)
            payload = json.loads(output_text)
            rows = payload["ranking"]
        except (ValueError, KeyError, TypeError) as exc:
            raise RankingJudgeUnavailable("OpenAI 排序检查响应不符合契约") from exc
        allowed = {str(row["object_id"]) for row in candidates}
        judgements = []
        for row in rows:
            object_id = str(row["object_id"])
            if object_id not in allowed:
                continue
            judgements.append(
                Judgement(
                    object_id=object_id,
                    rank=int(row["rank"]),
                    score=float(row["score"]),
                    confidence=float(row["confidence"]),
                    reason_codes=tuple(str(value) for value in row["reason_codes"]),
                    citation_locators=tuple(str(value) for value in row["citation_locators"]),
                )
            )
        return judgements


def _response_output_text(body: dict[str, Any]) -> str:
    for item in body.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text":
                value = content.get("text")
                if isinstance(value, str):
                    return value
    raise KeyError("output_text")
