"""模型网关入口。

调用方只依赖这里，不直接依赖具体提供者。所有输出先过契约校验再返回，
校验失败按 `ai_status = 解析失败` 处理并进人工队列，不抛给用户。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Protocol

from app.ai.contracts.validator import ValidationOutcome, validate
from app.ai.errors import ModelUnavailable
from app.ai.providers.http import HttpProvider
from app.ai.providers.local import LocalProvider
from app.ai.providers.mock import MockProvider
from app.core.config import Settings
from app.core.config import settings as default_settings


class Provider(Protocol):
    """提供者接口。

    签名写全而不用 **kwargs：网关是唯一的模型调用入口，参数写清楚才能让
    mypy 在换提供者时发现漏参，而不是在运行时才报 KeyError。
    """

    @property
    def model_version(self) -> str: ...

    @property
    def supports_repair(self) -> bool: ...

    def analyze_event_impact(
        self,
        *,
        document_id: str,
        security_id: str,
        segment_locator: str,
        segment_text: str,
        disclosure_time: str,
        thesis_id: str | None = ...,
        hypothesis_id: str | None = ...,
        thesis_context: str | None = ...,
        hypothesis_context: dict[str, Any] | None = ...,
        retrieval_context: list[tuple[str, str]] | None = ...,
        event_type: str = ...,
        occurred_on: str | None = ...,
        context: str = ...,
        repair_errors: list[str] | None = ...,
    ) -> dict[str, Any]: ...

    def draft_thesis(
        self,
        *,
        security_id: str,
        view: str,
        segments: list[tuple[str, str]],
        source_document_id: str | None = ...,
        investment_context: dict[str, Any] | None = ...,
        industry_metrics: list[dict[str, Any]] | None = ...,
        repair_errors: list[str] | None = ...,
    ) -> dict[str, Any]: ...

    def extract_events(
        self,
        *,
        document_id: str,
        segments: list[tuple[str, str]],
        disclosure_time: str,
    ) -> dict[str, Any]: ...

    def explain_metric(
        self,
        *,
        security_id: str,
        hypothesis_id: str,
        hypothesis: str,
        calc_result: dict[str, Any],
        repair_errors: list[str] | None = ...,
    ) -> dict[str, Any]: ...

    def draft_review(
        self,
        *,
        security_id: str,
        thesis_id: str,
        period_start: str,
        period_end: str,
        records: list[dict[str, Any]],
        repair_errors: list[str] | None = ...,
    ) -> dict[str, Any]: ...


@dataclass
class Gateway:
    """带校验的模型调用入口。"""

    settings: Settings
    provider: Provider

    @classmethod
    def build(cls, settings: Settings | None = None) -> Gateway:
        conf = settings or default_settings
        if conf.llm_provider == "local":
            return cls(settings=conf, provider=LocalProvider(conf))
        if conf.llm_provider == "mock":
            return cls(settings=conf, provider=MockProvider(conf))
        # 未配置端点时不静默退回 local：静默降级会让人以为在用真实模型，
        # 实际跑的是规则实现，进而污染模型评测结论。
        if not conf.llm_endpoint:
            raise ModelUnavailable("llm_provider=http 但未配置 LLM_ENDPOINT", retryable=False)
        return cls(settings=conf, provider=HttpProvider(conf))

    def event_impact(
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
        retrieval_context: list[tuple[str, str]] | None = None,
        event_type: str = "其他",
        occurred_on: str | None = None,
        context: str = "",
        repair_errors: list[str] | None = None,
    ) -> ValidationOutcome:
        return self._validate_with_repair(
            "event_impact",
            lambda errors: self.provider.analyze_event_impact(
                document_id=document_id,
                security_id=security_id,
                segment_locator=segment_locator,
                segment_text=segment_text,
                disclosure_time=disclosure_time,
                thesis_id=thesis_id,
                hypothesis_id=hypothesis_id,
                thesis_context=thesis_context,
                hypothesis_context=hypothesis_context,
                retrieval_context=retrieval_context,
                event_type=event_type,
                occurred_on=occurred_on,
                context=context,
                repair_errors=_merge_repair_errors(repair_errors, errors),
            ),
        )

    def extract_events(
        self,
        *,
        document_id: str,
        segments: list[tuple[str, str]],
        disclosure_time: str,
    ) -> ValidationOutcome:
        payload = self.provider.extract_events(
            document_id=document_id,
            segments=segments,
            disclosure_time=disclosure_time,
        )
        return validate("event_extraction", payload, thresholds=self.settings.rules)

    def thesis_draft(
        self,
        *,
        security_id: str,
        view: str,
        segments: list[tuple[str, str]],
        source_document_id: str | None = None,
        investment_context: dict[str, Any] | None = None,
        industry_metrics: list[dict[str, Any]] | None = None,
        repair_errors: list[str] | None = None,
    ) -> ValidationOutcome:
        return self._validate_with_repair(
            "thesis_draft",
            lambda errors: self.provider.draft_thesis(
                security_id=security_id,
                view=view,
                segments=segments,
                source_document_id=source_document_id,
                investment_context=investment_context,
                industry_metrics=industry_metrics,
                repair_errors=_merge_repair_errors(repair_errors, errors),
            ),
        )

    def metric_explain(
        self,
        *,
        security_id: str,
        hypothesis_id: str,
        hypothesis: str,
        calc_result: dict[str, Any],
        repair_errors: list[str] | None = None,
    ) -> ValidationOutcome:
        return self._validate_with_repair(
            "metric_explain",
            lambda errors: self.provider.explain_metric(
                security_id=security_id,
                hypothesis_id=hypothesis_id,
                hypothesis=hypothesis,
                calc_result=calc_result,
                repair_errors=_merge_repair_errors(repair_errors, errors),
            ),
        )

    def review_draft(
        self,
        *,
        security_id: str,
        thesis_id: str,
        period_start: str,
        period_end: str,
        records: list[dict[str, Any]],
        repair_errors: list[str] | None = None,
    ) -> ValidationOutcome:
        return self._validate_with_repair(
            "review_draft",
            lambda errors: self.provider.draft_review(
                security_id=security_id,
                thesis_id=thesis_id,
                period_start=period_start,
                period_end=period_end,
                records=records,
                repair_errors=_merge_repair_errors(repair_errors, errors),
            ),
        )

    def _validate_with_repair(
        self,
        schema_name: str,
        invoke: Callable[[list[str] | None], dict[str, Any]],
    ) -> ValidationOutcome:
        outcome = validate(schema_name, invoke(None), thresholds=self.settings.rules)
        if outcome.usable or not self.provider.supports_repair:
            return outcome
        repaired = validate(
            schema_name,
            invoke(outcome.errors),
            thresholds=self.settings.rules,
            allow_repair=False,
        )
        return replace(repaired, repaired=repaired.usable)


def _merge_repair_errors(
    requested: list[str] | None, validation: list[str] | None
) -> list[str] | None:
    errors = [*(requested or ()), *(validation or ())]
    return errors or None
