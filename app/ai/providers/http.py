"""OpenAI-compatible HTTP 模型提供者。

适配器只发送调用方明确提供的任务输入，不记录提示词正文和凭据；业务代码统一依赖
``Gateway``，不感知供应商特有的请求与响应结构。
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from app.ai.contracts.validator import load_schema
from app.ai.errors import ModelUnavailable
from app.ai.prompts.templates import (
    EVENT_EXTRACTION,
    EVENT_IMPACT,
    HYPOTHESIS_QUALITY,
    LOGIC_CHANGE_CONSOLIDATION,
    METRIC_EXPLAIN,
    METRIC_RECOMMEND,
    REVIEW_DRAFT,
    THESIS_DRAFT,
)
from app.core.config import Settings
from app.core.enums import AiStatus

# 兼容 AI 框架分支的既有导入名，并确保旧调用方捕获的是同一异常类型。
ProviderResponseError = ModelUnavailable


class HttpProvider:
    """OpenAI-compatible chat-completions 端点的同步适配器。"""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        async_client: httpx.AsyncClient | None = None,
    ) -> None:
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
        raw_endpoint = str(endpoint).rstrip("/")
        self._endpoint = (
            raw_endpoint
            if endpoint.path.rstrip("/").endswith("/chat/completions")
            else f"{raw_endpoint}/chat/completions"
        )
        self._is_deepseek = endpoint.host == "api.deepseek.com"
        if self._is_deepseek and settings.llm_api_key is None:
            raise ModelUnavailable("DeepSeek 端点必须配置 LLM_API_KEY", retryable=False)
        self._last_model_metadata: dict[str, Any] = {}
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(
                timeout=settings.llm_timeout_seconds,
                connect=settings.llm_connect_timeout_seconds,
                read=settings.llm_timeout_seconds,
                write=settings.llm_timeout_seconds,
                pool=settings.llm_connect_timeout_seconds,
            ),
            follow_redirects=False,
        )
        self._async_client = async_client or httpx.AsyncClient(
            timeout=httpx.Timeout(
                timeout=settings.llm_timeout_seconds,
                connect=settings.llm_connect_timeout_seconds,
                read=settings.llm_timeout_seconds,
                write=settings.llm_timeout_seconds,
                pool=settings.llm_connect_timeout_seconds,
            ),
            follow_redirects=False,
        )

    @property
    def model_version(self) -> str:
        return self._settings.llm_model_version

    @property
    def supports_repair(self) -> bool:
        return True

    def analyze_event_impact(
        self,
        *,
        document_id: str,
        security_id: str,
        segment_locator: str,
        segment_text: str,
        disclosure_time: str,
        candidates: list[dict[str, Any]],
        evidence_contexts: list[dict[str, Any]],
        event_type: str = "其他",
        occurred_on: str | None = None,
        repair_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        prompt = EVENT_IMPACT.render(
            event=segment_text,
            disclosure_time=disclosure_time,
            candidates=json.dumps(candidates, ensure_ascii=False, sort_keys=True),
            context=json.dumps(evidence_contexts, ensure_ascii=False, sort_keys=True),
        )
        payload = self._complete(
            system=EVENT_IMPACT.system,
            prompt=prompt,
            schema_name="event_impact",
            repair_errors=repair_errors,
        )
        payload.update(
            {
                "document_id": document_id,
                "security_id": security_id,
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
        impacts = payload.get("impacts")
        if isinstance(impacts, list):
            for impact in impacts:
                if not isinstance(impact, dict):
                    continue
                signal = impact.get("signal")
                if not isinstance(signal, dict):
                    continue
                signal["requires_human_review"] = True
                if impact.get("relevance") == "不相关":
                    signal["direction"] = "中性"
                    signal["impact_direction"] = "无关"
        return payload

    def analyze_event_impacts(
        self,
        *,
        document_id: str,
        security_id: str,
        events: list[dict[str, Any]],
        repair_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        """把同一资料的多个事件放进一次模型请求。"""
        prompt = _batch_event_impact_prompt(events)
        payload = self._complete(
            system=EVENT_IMPACT.system,
            prompt=prompt,
            schema_name="event_impact_batch",
            repair_errors=repair_errors,
        )
        return self._decorate_batch_payload(
            payload, document_id=document_id, security_id=security_id, events=events
        )

    async def analyze_event_impacts_async(
        self,
        *,
        document_id: str,
        security_id: str,
        events: list[dict[str, Any]],
        repair_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        """异步批量分析；取消协程时同时取消底层 HTTP 请求。"""
        prompt = _batch_event_impact_prompt(events)
        payload = await self._acomplete(
            system=EVENT_IMPACT.system,
            prompt=prompt,
            schema_name="event_impact_batch",
            repair_errors=repair_errors,
        )
        return self._decorate_batch_payload(
            payload, document_id=document_id, security_id=security_id, events=events
        )

    def _decorate_batch_payload(
        self,
        payload: dict[str, Any],
        *,
        document_id: str,
        security_id: str,
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        generated_at = datetime.now(UTC).isoformat()
        payload.update(
            {
                "model_version": self.model_version,
                "prompt_version": f"{EVENT_IMPACT.version}-batch-v1",
                "generated_at": generated_at,
                "ai_status": AiStatus.CANDIDATE.value,
            }
        )
        if self._last_model_metadata:
            payload["model_metadata"] = self._last_model_metadata
        inputs_by_id = {str(item["event_id"]): item for item in events}
        for result in payload.get("results", []):
            if not isinstance(result, dict) or not isinstance(result.get("analysis"), dict):
                continue
            analysis = result["analysis"]
            event_input = inputs_by_id.get(str(result.get("event_id")), {})
            analysis.setdefault("document_id", document_id)
            analysis.setdefault("security_id", security_id)
            analysis.setdefault("model_version", self.model_version)
            analysis.setdefault("prompt_version", f"{EVENT_IMPACT.version}-batch-v1")
            analysis.setdefault("generated_at", generated_at)
            analysis.setdefault("ai_status", AiStatus.CANDIDATE.value)
            if self._last_model_metadata:
                analysis.setdefault("model_metadata", self._last_model_metadata)
            event_payload = analysis.get("event")
            if isinstance(event_payload, dict):
                event_payload.update(
                    {
                        "event_id": str(result.get("event_id") or ""),
                        "event_type": str(event_input.get("event_type") or "其他"),
                        "event_time": event_input.get("occurred_on"),
                        "disclosure_time": event_input.get("disclosure_time"),
                        "fact": str(event_input.get("segment_text") or "")[:500],
                        "evidence_locator": event_input.get("segment_locator"),
                    }
                )
            for impact in analysis.get("impacts", []):
                if not isinstance(impact, dict) or not isinstance(impact.get("signal"), dict):
                    continue
                impact["signal"]["requires_human_review"] = True
                if impact.get("relevance") == "不相关":
                    impact["signal"]["direction"] = "中性"
                    impact["signal"]["impact_direction"] = "无关"
        return payload

    def extract_events(
        self,
        *,
        document_id: str,
        segments: list[tuple[str, str]],
        disclosure_time: str,
    ) -> dict[str, Any]:
        rendered = "\n".join(f"[{locator}] {text}" for locator, text in segments)
        prompt = EVENT_EXTRACTION.render(
            document_id=document_id,
            disclosure_time=disclosure_time,
            segments=rendered,
        )
        payload = self._complete(
            system=EVENT_EXTRACTION.system,
            prompt=prompt,
            schema_name="event_extraction",
        )
        return self._decorate_extraction(payload, document_id=document_id)

    async def extract_events_async(
        self,
        *,
        document_id: str,
        segments: list[tuple[str, str]],
        disclosure_time: str,
    ) -> dict[str, Any]:
        rendered = "\n".join(f"[{locator}] {text}" for locator, text in segments)
        prompt = EVENT_EXTRACTION.render(
            document_id=document_id,
            disclosure_time=disclosure_time,
            segments=rendered,
        )
        payload = await self._acomplete(
            system=EVENT_EXTRACTION.system,
            prompt=prompt,
            schema_name="event_extraction",
        )
        return self._decorate_extraction(payload, document_id=document_id)

    def _decorate_extraction(self, payload: dict[str, Any], *, document_id: str) -> dict[str, Any]:
        payload.update(
            {
                "document_id": document_id,
                "model_version": self.model_version,
                "prompt_version": EVENT_EXTRACTION.version,
                "generated_at": datetime.now(UTC).isoformat(),
                "ai_status": AiStatus.CANDIDATE.value,
            }
        )
        if self._last_model_metadata:
            payload["model_metadata"] = self._last_model_metadata
        return payload

    async def _acomplete(
        self,
        *,
        system: str,
        prompt: str,
        schema_name: str,
        repair_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        """异步 chat-completions 调用，供 worker 使用。"""
        self._last_model_metadata = {}
        started_at = time.perf_counter()
        headers = {"Content-Type": "application/json"}
        if self._settings.llm_api_key is not None:
            headers["Authorization"] = f"Bearer {self._settings.llm_api_key.get_secret_value()}"
        request = self._request_payload(
            system=system,
            prompt=prompt,
            schema_name=schema_name,
            repair_errors=repair_errors,
        )
        for attempt in range(self._settings.llm_max_retries + 1):
            try:
                response = await self._async_client.post(
                    self._endpoint, headers=headers, json=request
                )
            except httpx.TimeoutException as exc:
                if attempt >= self._settings.llm_max_retries:
                    raise ModelUnavailable(
                        f"模型请求超过 {self._settings.llm_timeout_seconds:g} 秒",
                        retryable=False,
                    ) from exc
                await asyncio.sleep(min(0.2 * (2**attempt), 1.0))
                continue
            except httpx.RequestError as exc:
                if attempt >= self._settings.llm_max_retries:
                    raise ModelUnavailable(f"模型端点网络失败: {type(exc).__name__}") from exc
                await asyncio.sleep(min(0.2 * (2**attempt), 1.0))
                continue
            if response.status_code in {408, 429} or response.status_code >= 500:
                if attempt < self._settings.llm_max_retries:
                    await asyncio.sleep(min(0.2 * (2**attempt), 1.0))
                    continue
                raise ModelUnavailable(f"模型端点暂不可用: HTTP {response.status_code}")
            decoded = self._decode_response(response, started_at=started_at, attempt=attempt)
            if decoded is not None:
                return decoded
            if attempt < self._settings.llm_max_retries:
                await asyncio.sleep(min(0.2 * (2**attempt), 1.0))
                continue
            raise ModelUnavailable("模型端点返回空 JSON 内容")
        raise ModelUnavailable("模型请求失败", retryable=False)

    def draft_thesis(
        self,
        *,
        security_id: str,
        view: str,
        segments: list[tuple[str, str]],
        source_document_id: str | None = None,
        investment_context: dict[str, Any] | None = None,
        industry_metrics: list[dict[str, Any]] | None = None,
        repair_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        rendered_segments = "\n".join(f"[{locator}] {text}" for locator, text in segments)
        prompt = THESIS_DRAFT.render(
            security=security_id,
            view=view,
            segments=rendered_segments or "无资料正文，仅整理研究员输入观点",
            investment_context=json.dumps(
                investment_context or {}, ensure_ascii=False, sort_keys=True
            ),
            industry_metrics=json.dumps(industry_metrics or [], ensure_ascii=False, sort_keys=True),
        )
        payload = self._complete(
            system=THESIS_DRAFT.system,
            prompt=prompt,
            schema_name="thesis_draft",
            repair_errors=repair_errors,
        )
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

    def explain_metric(
        self,
        *,
        security_id: str,
        hypothesis_id: str,
        hypothesis: str,
        calc_result: dict[str, Any],
        repair_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        prompt = METRIC_EXPLAIN.render(
            hypothesis=hypothesis,
            calc_result=json.dumps(calc_result, ensure_ascii=False, sort_keys=True),
        )
        payload = self._complete(
            system=METRIC_EXPLAIN.system,
            prompt=prompt,
            schema_name="metric_explain",
            repair_errors=repair_errors,
        )
        payload.setdefault("security_id", security_id)
        payload.setdefault("hypothesis_id", hypothesis_id)
        payload.setdefault("calculation_source", "app.calc")
        return self._metadata(payload, prompt_version=METRIC_EXPLAIN.version)

    def recommend_metrics(
        self,
        *,
        security_id: str,
        hypothesis_id: str,
        hypothesis: str,
        industry: str,
        catalog_version: str,
        candidates: list[dict[str, Any]],
        top_k: int,
        repair_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        """让远程模型在工具召回的规范指标集合内完成关联判断。"""
        prompt = METRIC_RECOMMEND.render(
            security_id=security_id,
            industry=industry or "未提供",
            hypothesis_id=hypothesis_id,
            hypothesis=hypothesis,
            catalog_version=catalog_version,
            candidates=json.dumps(candidates, ensure_ascii=False, sort_keys=True),
            top_k=str(max(1, min(top_k, 20))),
        )
        payload = self._complete(
            system=METRIC_RECOMMEND.system,
            prompt=prompt,
            schema_name="metric_recommend",
            repair_errors=repair_errors,
        )
        payload.setdefault("security_id", security_id)
        payload.setdefault("hypothesis_id", hypothesis_id)
        payload.setdefault("catalog_version", catalog_version)
        payload.setdefault("requires_human_review", True)
        return self._metadata(payload, prompt_version=METRIC_RECOMMEND.version)

    def draft_review(
        self,
        *,
        security_id: str,
        thesis_id: str,
        period_start: str,
        period_end: str,
        records: list[dict[str, Any]],
        repair_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        prompt = REVIEW_DRAFT.render(
            security=security_id,
            thesis_id=thesis_id,
            period_start=period_start,
            period_end=period_end,
            records=json.dumps(records, ensure_ascii=False, sort_keys=True),
        )
        payload = self._complete(
            system=REVIEW_DRAFT.system,
            prompt=prompt,
            schema_name="review_draft",
            repair_errors=repair_errors,
        )
        for key, value in (
            ("security_id", security_id),
            ("thesis_id", thesis_id),
            ("period_start", period_start),
            ("period_end", period_end),
        ):
            payload.setdefault(key, value)
        payload.setdefault("requires_human_review", True)
        return self._metadata(payload, prompt_version=REVIEW_DRAFT.version)

    def hypothesis_quality(
        self,
        *,
        security_id: str,
        thesis_id: str,
        title: str,
        core_view: str,
        hypotheses: list[dict[str, Any]],
        repair_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        prompt = HYPOTHESIS_QUALITY.render(
            security=security_id,
            title=title,
            core_view=core_view,
            hypotheses=json.dumps(hypotheses, ensure_ascii=False, sort_keys=True),
        )
        payload = self._complete(
            system=HYPOTHESIS_QUALITY.system,
            prompt=prompt,
            schema_name="hypothesis_quality",
            repair_errors=repair_errors,
        )
        payload.setdefault("thesis_id", thesis_id)
        payload.setdefault("requires_human_review", True)
        return self._metadata(payload, prompt_version=HYPOTHESIS_QUALITY.version)

    def consolidate_logic_change(
        self,
        *,
        security_id: str,
        thesis_id: str,
        business_date: str,
        thesis_core_view: str,
        hypotheses: list[dict[str, Any]],
        candidate_evidence: list[dict[str, Any]],
        repair_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        prompt = LOGIC_CHANGE_CONSOLIDATION.render(
            business_date=business_date,
            security_id=security_id,
            thesis_id=thesis_id,
            thesis_core_view=thesis_core_view,
            hypotheses=json.dumps(hypotheses, ensure_ascii=False, sort_keys=True),
            candidate_evidence=json.dumps(candidate_evidence, ensure_ascii=False, sort_keys=True),
        )
        payload = self._complete(
            system=LOGIC_CHANGE_CONSOLIDATION.system,
            prompt=prompt,
            schema_name="logic_change_consolidation",
            repair_errors=repair_errors,
        )
        for key, value in (
            ("security_id", security_id),
            ("thesis_id", thesis_id),
            ("business_date", business_date),
        ):
            payload.setdefault(key, value)
        payload.setdefault("requires_human_review", True)
        return self._metadata(payload, prompt_version=LOGIC_CHANGE_CONSOLIDATION.version)

    async def consolidate_logic_change_async(
        self,
        *,
        security_id: str,
        thesis_id: str,
        business_date: str,
        thesis_core_view: str,
        hypotheses: list[dict[str, Any]],
        candidate_evidence: list[dict[str, Any]],
        repair_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        prompt = LOGIC_CHANGE_CONSOLIDATION.render(
            business_date=business_date,
            security_id=security_id,
            thesis_id=thesis_id,
            thesis_core_view=thesis_core_view,
            hypotheses=json.dumps(hypotheses, ensure_ascii=False, sort_keys=True),
            candidate_evidence=json.dumps(candidate_evidence, ensure_ascii=False, sort_keys=True),
        )
        payload = await self._acomplete(
            system=LOGIC_CHANGE_CONSOLIDATION.system,
            prompt=prompt,
            schema_name="logic_change_consolidation",
            repair_errors=repair_errors,
        )
        for key, value in (
            ("security_id", security_id),
            ("thesis_id", thesis_id),
            ("business_date", business_date),
        ):
            payload.setdefault(key, value)
        payload.setdefault("requires_human_review", True)
        return self._metadata(payload, prompt_version=LOGIC_CHANGE_CONSOLIDATION.version)

    def _complete(
        self,
        *,
        system: str,
        prompt: str,
        schema_name: str,
        repair_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        self._last_model_metadata = {}
        started_at = time.perf_counter()
        headers = {"Content-Type": "application/json"}
        if self._settings.llm_api_key is not None:
            headers["Authorization"] = f"Bearer {self._settings.llm_api_key.get_secret_value()}"
        request = self._request_payload(
            system=system,
            prompt=prompt,
            schema_name=schema_name,
            repair_errors=repair_errors,
        )

        for attempt in range(self._settings.llm_max_retries + 1):
            try:
                response = self._client.post(
                    self._endpoint,
                    headers=headers,
                    json=request,
                )
            except httpx.TimeoutException as exc:
                if attempt >= self._settings.llm_max_retries:
                    raise ModelUnavailable(
                        f"模型请求超过 {self._settings.llm_timeout_seconds:g} 秒",
                        retryable=False,
                    ) from exc
                time.sleep(min(0.2 * (2**attempt), 1.0))
                continue
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
            decoded = self._decode_response(response, started_at=started_at, attempt=attempt)
            if decoded is not None:
                return decoded
            if attempt < self._settings.llm_max_retries:
                time.sleep(min(0.2 * (2**attempt), 1.0))
                continue
            raise ModelUnavailable("模型端点返回空 JSON 内容")

        raise ModelUnavailable("模型端点未返回响应")

    def _request_payload(
        self,
        *,
        system: str,
        prompt: str,
        schema_name: str,
        repair_errors: list[str] | None,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self.model_version,
            "messages": [
                {"role": "system", "content": _system_with_contract(system, schema_name)},
                {"role": "user", "content": _instruction_with_repair(prompt, repair_errors)},
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
        return request

    def _decode_response(
        self, response: httpx.Response, *, started_at: float, attempt: int
    ) -> dict[str, Any] | None:
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
            return None
        if cleaned.startswith("```"):
            cleaned = cleaned.removeprefix("```json").removeprefix("```")
            cleaned = cleaned.removesuffix("```").strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            return {"provider_raw_text": content}
        return parsed if isinstance(parsed, dict) else {"provider_raw_output": parsed}

    def _metadata(self, payload: dict[str, Any], *, prompt_version: str) -> dict[str, Any]:
        result = dict(payload)
        # 版本和生成时间是网关的审计字段，不接受模型在正文 JSON 中的自报值，
        # 否则模型幻觉的 "1.0.0" 会污染可追溯性和后续评测分桶。
        result["model_version"] = self.model_version
        result["prompt_version"] = prompt_version
        result["generated_at"] = datetime.now(UTC).isoformat()
        # 解析成功与否由网关的契约校验决定，不能接受模型在正文里自报“解析失败”。
        result["ai_status"] = AiStatus.CANDIDATE.value
        return result


def _batch_event_impact_prompt(events: list[dict[str, Any]]) -> str:
    """Tell compatible models about both layers of the batch JSON structure.

    The outer schema intentionally keeps ``analysis`` open-ended so the server
    can decorate it with stable IDs.  Without this concrete nested example,
    some providers flatten signal fields into ``analysis`` and the following
    per-event ``event_impact`` validation correctly rejects the response.
    """

    return (
        "请批量判断以下事件分别与其候选假设的关系。每个输入事件必须返回且仅返回一次，"
        "results 顺序必须与输入一致；不得把不同事件的事实、引用或结论混合。\n\n"
        "只输出一个 JSON 对象，顶层只能包含 results。严格使用以下嵌套：\n"
        '{"results":[{"event_id":"输入 event_id","analysis":{'
        '"event":{"event_type":"订单|政策|管理层表述|业绩|其他",'
        '"disclosure_time":"输入时间","fact":"仅输入事实",'
        '"evidence_locator":"输入 locator"},'
        '"impacts":[{"thesis_id":"输入 thesis_id","hypothesis_id":"输入 hypothesis_id",'
        '"relevance":"相关|不相关|待定","inference":"简洁推断",'
        '"citations":["输入 locator"],"unsupported_claims":[],"'
        '"signal":{"direction":"正向|负向|中性|不确定",'
        '"impact_direction":"支持|冲突|中性|无关","strength":0.0,"confidence":0.0,'
        '"horizon":"短期|中期|长期|null","rationale":"依据",'
        '"transmission_path":"事实 → 变量 → 假设",'
        '"suggested_tracking":[],"requires_human_review":true}}]}}]}'
        "\n\n特别禁止：不得把 relevance、citations、direction、impact_direction、"
        "strength、confidence、rationale、transmission_path 或 requires_human_review "
        "直接放在 analysis 顶层；它们必须位于 analysis.impacts[i] 中，"
        "其中方向、强度、置信度等字段必须位于 analysis.impacts[i].signal 中。\n\n"
        "输入事件：\n" + json.dumps(events, ensure_ascii=False, sort_keys=True)
    )


def _normalize_thesis_references(payload: dict[str, Any]) -> None:
    """删除不是稳定假设标识的数字草稿索引。

    模型可能把 ``hypothesis_ref`` 误解为数组下标；草稿假设 ID 尚未分配时保留该值
    会制造错误关联，因此这一阶段只有字符串 ID 或 null 具有业务含义。
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


def _system_with_contract(system: str, schema_name: str) -> str:
    contract = _compact_schema(load_schema(schema_name))
    return (
        f"{system}\n\n"
        "你必须输出一个 JSON 对象，且必须满足以下完整输出契约。"
        "不要输出 Markdown、代码围栏或契约之外的字段。\n"
        f"JSON Schema ({schema_name}):\n{json.dumps(contract, ensure_ascii=False)}"
    )


def _instruction_with_repair(instruction: str, repair_errors: list[str] | None) -> str:
    if not repair_errors:
        return instruction
    issues = "\n".join(f"- {error}" for error in repair_errors[:10])
    return (
        f"{instruction}\n\n"
        "上一次输出未通过契约或证据校验。请仅根据已给输入重写完整 JSON；"
        "不要补造事实、引用或数值。必须修复：\n"
        f"{issues}"
    )


def _compact_schema(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _compact_schema(item)
            for key, item in value.items()
            if key not in {"$schema", "$id", "title", "description"}
        }
    if isinstance(value, list):
        return [_compact_schema(item) for item in value]
    return value


HttpLLMProvider = HttpProvider
