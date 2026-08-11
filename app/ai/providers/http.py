"""OpenAI-compatible HTTP 模型 Provider。

兼容基础 URL 与完整 ``/chat/completions`` URL；业务代码只依赖 Gateway，
网络失败通过 ModelUnavailable 交给队列决定是否重试。
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.ai.errors import ModelUnavailable
from app.ai.prompts.templates import EVENT_IMPACT, METRIC_EXPLAIN, REVIEW_DRAFT, THESIS_DRAFT
from app.core.config import Settings
from app.core.enums import AiStatus


# 旧名称必须指向同一异常类，旧调用方的 except 才能捕获新 Provider 的失败。
ProviderResponseError = ModelUnavailable


def _secret_value(value: object | None) -> str | None:
    if value is None:
        return None
    getter = getattr(value, "get_secret_value", None)
    return str(getter() if callable(getter) else value)


class HttpProvider:
    """同步调用 OpenAI-compatible chat-completions 端点。"""

    def __init__(self, settings: Settings, *, client: httpx.Client | None = None) -> None:
        if not settings.llm_endpoint:
            raise ModelUnavailable(
                "llm_provider=http 但未配置 LLM_ENDPOINT",
                retryable=False,
            )
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
        raw_endpoint = str(endpoint).rstrip("/")
        self._endpoint = (
            raw_endpoint
            if endpoint.path.rstrip("/").endswith("/chat/completions")
            else f"{raw_endpoint}/chat/completions"
        )
        self._settings = settings
        self._is_deepseek = endpoint.host == "api.deepseek.com"
        if self._is_deepseek and _secret_value(settings.llm_api_key) is None:
            raise ModelUnavailable(
                "DeepSeek 端点必须配置 LLM_API_KEY",
                retryable=False,
            )
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
        context: str = "",
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
            context=context or "仅使用调用方提供的上下文；当前没有额外检索片段。",
        )
        payload = self._complete(system=EVENT_IMPACT.system, instruction=prompt)
        relevance = payload.get("relevance")
        payload.update(
            {
                "document_id": document_id,
                "security_id": security_id,
                "thesis_id": None if relevance == "不相关" else thesis_id,
                "hypothesis_id": None if relevance == "不相关" else hypothesis_id,
            }
        )
        event = payload.setdefault("event", {})
        if isinstance(event, dict):
            event.setdefault("event_type", event_type)
            event.setdefault("event_time", occurred_on)
            event.setdefault("disclosure_time", disclosure_time)
            event.setdefault("evidence_locator", segment_locator)
        signal = payload.get("signal")
        if isinstance(signal, dict):
            signal["requires_human_review"] = True
            if relevance == "不相关":
                signal["direction"] = "中性"
                signal["impact_direction"] = "无关"
        return self._metadata(
            payload,
            prompt_version=EVENT_IMPACT.version,
            include_provider_metadata=True,
        )

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
        payload = self._complete(system=THESIS_DRAFT.system, instruction=prompt)
        _normalize_thesis_references(payload)
        payload.setdefault("security_id", security_id)
        payload.setdefault("source_document_id", source_document_id)
        return self._metadata(
            payload,
            prompt_version=THESIS_DRAFT.version,
            include_provider_metadata=True,
        )

    def explain_metric(
        self,
        *,
        security_id: str,
        hypothesis_id: str,
        hypothesis: str,
        calc_result: dict[str, Any],
    ) -> dict[str, Any]:
        prompt = METRIC_EXPLAIN.render(
            hypothesis=hypothesis,
            calc_result=json.dumps(calc_result, ensure_ascii=False, sort_keys=True),
        )
        payload = self._complete(system=METRIC_EXPLAIN.system, instruction=prompt)
        payload.setdefault("security_id", security_id)
        payload.setdefault("hypothesis_id", hypothesis_id)
        payload.setdefault("calculation_source", "app.calc")
        return self._metadata(payload, prompt_version=METRIC_EXPLAIN.version)

    def draft_review(
        self,
        *,
        security_id: str,
        thesis_id: str,
        period_start: str,
        period_end: str,
        records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        prompt = REVIEW_DRAFT.render(
            security=security_id,
            thesis_id=thesis_id,
            period_start=period_start,
            period_end=period_end,
            records=json.dumps(records, ensure_ascii=False, sort_keys=True),
        )
        payload = self._complete(system=REVIEW_DRAFT.system, instruction=prompt)
        for key, value in (
            ("security_id", security_id),
            ("thesis_id", thesis_id),
            ("period_start", period_start),
            ("period_end", period_end),
        ):
            payload.setdefault(key, value)
        payload.setdefault("requires_human_review", True)
        return self._metadata(payload, prompt_version=REVIEW_DRAFT.version)

    def _complete(self, *, system: str, instruction: str) -> dict[str, Any]:
        self._last_model_metadata = {}
        headers = {"Content-Type": "application/json"}
        api_key = _secret_value(self._settings.llm_api_key)
        if api_key is not None:
            headers["Authorization"] = f"Bearer {api_key}"
        request: dict[str, Any] = {
            "model": self.model_version,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": instruction},
            ],
            "stream": False,
            "max_tokens": int(getattr(self._settings, "llm_max_output_tokens", 4096)),
            "response_format": {"type": "json_object"},
        }
        thinking_mode = str(getattr(self._settings, "llm_thinking_mode", "disabled"))
        if thinking_mode == "disabled":
            request["temperature"] = 0
        if self._is_deepseek:
            request["thinking"] = {"type": thinking_mode}
            if thinking_mode == "enabled":
                request["reasoning_effort"] = str(
                    getattr(self._settings, "llm_reasoning_effort", "low")
                )

        max_retries = int(self._settings.llm_max_retries)
        started_at = time.perf_counter()
        for attempt in range(max_retries + 1):
            try:
                response = self._client.post(
                    self._endpoint,
                    headers=headers,
                    json=request,
                )
            except httpx.RequestError as exc:
                if attempt < max_retries:
                    time.sleep(min(0.2 * (2**attempt), 1.0))
                    continue
                raise ModelUnavailable(f"模型端点网络失败: {type(exc).__name__}") from exc

            if response.status_code in {408, 429} or response.status_code >= 500:
                if attempt < max_retries:
                    time.sleep(min(0.2 * (2**attempt), 1.0))
                    continue
                raise ModelUnavailable(f"模型端点暂不可用: HTTP {response.status_code}")
            if response.is_error:
                raise ModelUnavailable(
                    f"模型端点拒绝请求: HTTP {response.status_code}",
                    retryable=False,
                )
            try:
                body = response.json()
                content = body["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise ModelUnavailable(
                    "模型端点响应不符合 chat-completions 契约",
                    retryable=False,
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
                    "latency_ms": int((time.perf_counter() - started_at) * 1000),
                    "attempt_count": attempt + 1,
                }.items()
                if value is not None
            }
            if isinstance(content, dict):
                return content
            if not isinstance(content, str):
                return {"provider_raw_text": str(content)}
            cleaned = content.strip()
            if not cleaned:
                if attempt < max_retries:
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

    def _metadata(
        self,
        payload: dict[str, Any],
        *,
        prompt_version: str,
        include_provider_metadata: bool = False,
    ) -> dict[str, Any]:
        result = dict(payload)
        result.setdefault("model_version", self.model_version)
        result.setdefault("prompt_version", prompt_version)
        result.setdefault("generated_at", datetime.now(timezone.utc).isoformat())
        result.setdefault("ai_status", AiStatus.CANDIDATE.value)
        if include_provider_metadata and self._last_model_metadata:
            result["model_metadata"] = self._last_model_metadata
        return result


def _normalize_thesis_references(payload: dict[str, Any]) -> None:
    suggestions = payload.get("invalidation_suggestions")
    if not isinstance(suggestions, list):
        return
    for suggestion in suggestions:
        if not isinstance(suggestion, dict):
            continue
        reference = suggestion.get("hypothesis_ref")
        if reference is not None and not isinstance(reference, str):
            suggestion["hypothesis_ref"] = None


# 旧 AI 分支使用该类名；保留别名避免已有调用方在合并后失效。
HttpLLMProvider = HttpProvider
