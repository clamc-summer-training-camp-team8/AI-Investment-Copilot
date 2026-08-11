"""OpenAI-compatible HTTP model provider.

The adapter sends only task inputs supplied by the caller and never logs prompt
content or credentials.  Business code continues to depend on ``Gateway`` and
is therefore isolated from vendor-specific response shapes.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from app.ai.errors import ModelUnavailable
from app.ai.prompts.templates import EVENT_IMPACT, THESIS_DRAFT
from app.core.config import Settings
from app.core.enums import AiStatus


class HttpProvider:
    """Synchronous adapter for an OpenAI-compatible chat-completions endpoint."""

    def __init__(self, settings: Settings, *, client: httpx.Client | None = None) -> None:
        if not settings.llm_endpoint:
            raise ModelUnavailable("llm_provider=http 但未配置 LLM_ENDPOINT", retryable=False)
        endpoint = httpx.URL(settings.llm_endpoint)
        is_loopback_http = endpoint.scheme == "http" and endpoint.host in {
            "127.0.0.1",
            "localhost",
            "::1",
        }
        if endpoint.scheme != "https" and not is_loopback_http:
            raise ModelUnavailable(
                "LLM_ENDPOINT 必须使用 HTTPS；仅本机回环地址允许 HTTP",
                retryable=False,
            )
        self._settings = settings
        self._endpoint = str(endpoint)
        self._is_deepseek = endpoint.host == "api.deepseek.com"
        if self._is_deepseek and settings.llm_api_key is None:
            raise ModelUnavailable("DeepSeek 端点必须配置 LLM_API_KEY", retryable=False)
        self._last_model_metadata: dict[str, Any] = {}
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(settings.llm_timeout_seconds),
            follow_redirects=False,
        )

    @property
    def model_version(self) -> str:
        return self._settings.llm_model_version

    def analyze_event_impact(
        self,
        *,
        document_id: str,
        security_id: str,
        segment_locator: str,
        segment_text: str,
        disclosure_time: str,
        thesis_id: str | None = None,
        hypothesis_id: str | None = None,
        thesis_context: str | None = None,
        hypothesis_context: dict[str, Any] | None = None,
        event_type: str = "其他",
        occurred_on: str | None = None,
    ) -> dict[str, Any]:
        prompt = EVENT_IMPACT.render(
            event=segment_text,
            disclosure_time=disclosure_time,
            candidates=json.dumps(
                {
                    "thesis_id": thesis_id,
                    "thesis_view": thesis_context,
                    "hypothesis_id": hypothesis_id,
                    "hypothesis": hypothesis_context,
                },
                ensure_ascii=False,
            ),
            context="无额外上下文",
        )
        payload = self._complete(system=EVENT_IMPACT.system, prompt=prompt)
        relevance = payload.get("relevance")
        resolved_thesis_id = None if relevance == "不相关" else thesis_id
        resolved_hypothesis_id = None if relevance == "不相关" else hypothesis_id
        payload.update(
            {
                "document_id": document_id,
                "security_id": security_id,
                "thesis_id": resolved_thesis_id,
                "hypothesis_id": resolved_hypothesis_id,
                "model_version": self.model_version,
                "prompt_version": EVENT_IMPACT.version,
                "generated_at": datetime.now(UTC).isoformat(),
                "ai_status": AiStatus.CANDIDATE.value,
            }
        )
        if self._last_model_metadata:
            payload["model_metadata"] = self._last_model_metadata
        event = payload.get("event")
        if isinstance(event, dict):
            event.update(
                {
                    "event_type": event_type,
                    "event_time": occurred_on,
                    "disclosure_time": disclosure_time,
                    "evidence_locator": segment_locator,
                }
            )
        signal = payload.get("signal")
        if isinstance(signal, dict):
            signal["requires_human_review"] = True
            if relevance == "不相关":
                signal["direction"] = "中性"
                signal["impact_direction"] = "无关"
        return payload

    def draft_thesis(
        self,
        *,
        security_id: str,
        view: str,
        segments: list[tuple[str, str]],
        source_document_id: str | None = None,
    ) -> dict[str, Any]:
        rendered_segments = "\n".join(f"[{locator}] {text}" for locator, text in segments)
        prompt = THESIS_DRAFT.render(
            security=security_id,
            view=view,
            segments=rendered_segments or "无资料正文，仅整理研究员输入观点",
        )
        payload = self._complete(system=THESIS_DRAFT.system, prompt=prompt)
        _normalize_thesis_references(payload)
        payload.update(
            {
                "source_document_id": source_document_id,
                "security_id": security_id,
                "model_version": self.model_version,
                "prompt_version": THESIS_DRAFT.version,
                "generated_at": datetime.now(UTC).isoformat(),
                "ai_status": AiStatus.CANDIDATE.value,
            }
        )
        if self._last_model_metadata:
            payload["model_metadata"] = self._last_model_metadata
        return payload

    def _complete(self, *, system: str, prompt: str) -> dict[str, Any]:
        self._last_model_metadata = {}
        headers = {"Content-Type": "application/json"}
        if self._settings.llm_api_key is not None:
            headers["Authorization"] = f"Bearer {self._settings.llm_api_key.get_secret_value()}"
        request = {
            "model": self.model_version,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "max_tokens": self._settings.llm_max_output_tokens,
            "response_format": {"type": "json_object"},
        }
        if self._settings.llm_thinking_mode == "disabled":
            request["temperature"] = 0
        if self._is_deepseek:
            request["thinking"] = {"type": self._settings.llm_thinking_mode}
            if self._settings.llm_thinking_mode == "enabled":
                request["reasoning_effort"] = self._settings.llm_reasoning_effort

        for attempt in range(self._settings.llm_max_retries + 1):
            try:
                response = self._client.post(
                    self._endpoint,
                    headers=headers,
                    json=request,
                )
            except httpx.RequestError as exc:
                if attempt >= self._settings.llm_max_retries:
                    raise ModelUnavailable(f"模型端点网络失败: {type(exc).__name__}") from exc
                time.sleep(min(0.2 * (2**attempt), 1.0))
                continue

            if response.status_code in {408, 429} or response.status_code >= 500:
                if attempt < self._settings.llm_max_retries:
                    time.sleep(min(0.2 * (2**attempt), 1.0))
                    continue
                raise ModelUnavailable(f"模型端点暂不可用: HTTP {response.status_code}")
            if response.is_error:
                raise ModelUnavailable(
                    f"模型端点拒绝请求: HTTP {response.status_code}", retryable=False
                )
            try:
                body = response.json()
                content = body["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise ModelUnavailable(
                    "模型端点响应不符合 chat-completions 契约", retryable=False
                ) from exc
            finish_reason = body["choices"][0].get("finish_reason")
            if finish_reason == "length":
                raise ModelUnavailable(
                    "模型 JSON 输出被长度上限截断，请提高 LLM_MAX_OUTPUT_TOKENS",
                    retryable=False,
                )
            self._last_model_metadata = {
                key: value
                for key, value in {
                    "provider": "deepseek" if self._is_deepseek else "openai-compatible",
                    "request_id": body.get("id"),
                    "usage": body.get("usage"),
                    "finish_reason": finish_reason,
                }.items()
                if value is not None
            }
            if isinstance(content, dict):
                return content
            if not isinstance(content, str):
                return {"provider_raw_text": str(content)}
            cleaned = content.strip()
            if not cleaned:
                if attempt < self._settings.llm_max_retries:
                    time.sleep(min(0.2 * (2**attempt), 1.0))
                    continue
                raise ModelUnavailable("模型端点返回空 JSON 内容")
            if cleaned.startswith("```"):
                cleaned = cleaned.removeprefix("```json").removeprefix("```")
                cleaned = cleaned.removesuffix("```").strip()
            try:
                parsed = json.loads(cleaned)
            except json.JSONDecodeError:
                return {"provider_raw_text": content}
            return parsed if isinstance(parsed, dict) else {"provider_raw_output": parsed}

        raise ModelUnavailable("模型端点未返回响应")


def _normalize_thesis_references(payload: dict[str, Any]) -> None:
    """Drop numeric draft indices that are not stable hypothesis identifiers.

    DeepSeek can interpret ``hypothesis_ref`` as an array index even when the
    example uses null. Draft hypothesis IDs are assigned only after validation,
    so retaining such an index would create a false link. Null is the only
    semantically valid value at this stage.
    """
    suggestions = payload.get("invalidation_suggestions")
    if not isinstance(suggestions, list):
        return
    for suggestion in suggestions:
        if not isinstance(suggestion, dict):
            continue
        reference = suggestion.get("hypothesis_ref")
        if reference is not None and not isinstance(reference, str):
            suggestion["hypothesis_ref"] = None
