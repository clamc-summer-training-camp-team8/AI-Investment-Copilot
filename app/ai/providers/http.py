"""OpenAI-compatible 私有模型 Provider。

只负责协议适配，不负责业务状态和数据库写入。真实部署地址、密钥、超时和重试
均由 Settings 注入，便于在不改业务层的情况下替换模型服务。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx

from app.ai.prompts.templates import EVENT_IMPACT, THESIS_DRAFT
from app.core.config import Settings


class ProviderResponseError(RuntimeError):
    """模型不可用或返回内容无法解析为 JSON。"""


class HttpLLMProvider:
    """调用 OpenAI-compatible `/chat/completions` 接口。"""

    def __init__(self, settings: Settings, *, client: httpx.Client | None = None) -> None:
        if not settings.llm_endpoint:
            raise ProviderResponseError("http Provider 缺少 LLM_ENDPOINT")
        self._settings = settings
        self._endpoint = settings.llm_endpoint.rstrip("/")
        self._client = client or httpx.Client(timeout=settings.llm_timeout_seconds)

    @property
    def model_version(self) -> str:
        return self._settings.llm_model_version

    def _call(self, *, system: str, instruction: str) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self._settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self._settings.llm_api_key}"
        request = {
            "model": self.model_version,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": instruction},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        url = f"{self._endpoint}/chat/completions"
        last_error: Exception | None = None
        for _ in range(self._settings.llm_max_retries + 1):
            try:
                response = self._client.post(url, headers=headers, json=request)
                response.raise_for_status()
                body = response.json()
                content = body["choices"][0]["message"]["content"]
                payload = json.loads(content)
                if not isinstance(payload, dict):
                    raise TypeError("模型 JSON 顶层必须是 object")
                return payload
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
                last_error = exc
        raise ProviderResponseError(f"模型调用或 JSON 解析失败: {last_error}") from last_error

    def _metadata(self, payload: dict[str, Any], *, prompt_version: str) -> dict[str, Any]:
        result = dict(payload)
        result.setdefault("model_version", self.model_version)
        result.setdefault("prompt_version", prompt_version)
        result.setdefault("generated_at", datetime.now(timezone.utc).isoformat())
        return result

    def analyze_event_impact(self, **kwargs: Any) -> dict[str, Any]:
        prompt = EVENT_IMPACT.render(
            event=kwargs["segment_text"],
            disclosure_time=kwargs["disclosure_time"],
            candidates=(
                f"thesis_id={kwargs.get('thesis_id')}; "
                f"hypothesis_id={kwargs.get('hypothesis_id')}; "
                f"event_type={kwargs.get('event_type')}"
            ),
            context=kwargs.get("context") or "仅使用调用方提供的上下文；当前版本未额外注入事实。",
        )
        payload = self._call(system=EVENT_IMPACT.system, instruction=prompt)
        payload.setdefault("document_id", kwargs["document_id"])
        payload.setdefault("security_id", kwargs["security_id"])
        payload.setdefault("event", {})
        payload["event"].setdefault("disclosure_time", kwargs["disclosure_time"])
        payload["event"].setdefault("evidence_locator", kwargs["segment_locator"])
        return self._metadata(payload, prompt_version=EVENT_IMPACT.version)

    def draft_thesis(self, **kwargs: Any) -> dict[str, Any]:
        segments = "\\\\n".join(f"{locator}: {content}" for locator, content in kwargs["segments"])
        prompt = THESIS_DRAFT.render(
            security=kwargs["security_id"],
            view=kwargs["view"],
            segments=segments,
        )
        payload = self._call(system=THESIS_DRAFT.system, instruction=prompt)
        payload.setdefault("security_id", kwargs["security_id"])
        payload.setdefault("source_document_id", kwargs.get("source_document_id"))
        return self._metadata(payload, prompt_version=THESIS_DRAFT.version)
