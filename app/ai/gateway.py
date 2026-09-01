"""模型网关入口。

调用方只依赖这里，不直接依赖具体提供者。所有输出先过契约校验再返回，
校验失败按 `ai_status = 解析失败` 处理并进人工队列，不抛给用户。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any, Protocol

from app.ai.contracts.validator import ValidationOutcome, validate
from app.ai.errors import ModelUnavailable
from app.ai.providers.http import HttpProvider
from app.ai.providers.local import LocalProvider
from app.ai.providers.mock import MockProvider
from app.core.config import Settings
from app.core.config import settings as default_settings
from app.core.enums import AiStatus


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
        candidates: list[dict[str, Any]],
        evidence_contexts: list[dict[str, Any]],
        event_type: str = ...,
        occurred_on: str | None = ...,
        repair_errors: list[str] | None = ...,
    ) -> dict[str, Any]: ...

    def analyze_event_impacts(
        self,
        *,
        document_id: str,
        security_id: str,
        events: list[dict[str, Any]],
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

    def hypothesis_quality(
        self,
        *,
        security_id: str,
        thesis_id: str,
        title: str,
        core_view: str,
        hypotheses: list[dict[str, Any]],
        repair_errors: list[str] | None = ...,
    ) -> dict[str, Any]: ...

    def consolidate_logic_change(
        self,
        *,
        security_id: str,
        thesis_id: str,
        business_date: str,
        thesis_core_view: str,
        hypotheses: list[dict[str, Any]],
        candidate_evidence: list[dict[str, Any]],
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
        candidates: list[dict[str, Any]],
        evidence_contexts: list[dict[str, Any]],
        event_type: str = "其他",
        occurred_on: str | None = None,
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
                candidates=candidates,
                evidence_contexts=evidence_contexts,
                event_type=event_type,
                occurred_on=occurred_on,
                repair_errors=_merge_repair_errors(repair_errors, errors),
            ),
        )

    def event_impacts(
        self,
        *,
        document_id: str,
        security_id: str,
        events: list[dict[str, Any]],
        repair_errors: list[str] | None = None,
    ) -> list[ValidationOutcome]:
        """一次模型请求分析多个事件；每个子结果仍按 event_impact 契约校验。"""
        aggregate = self._validate_with_repair(
            "event_impact_batch",
            lambda errors: self.provider.analyze_event_impacts(
                document_id=document_id,
                security_id=security_id,
                events=events,
                repair_errors=_merge_repair_errors(repair_errors, errors),
            ),
        )
        return self._split_batch_outcomes(events, aggregate)

    async def event_impacts_async(
        self,
        *,
        document_id: str,
        security_id: str,
        events: list[dict[str, Any]],
        repair_errors: list[str] | None = None,
    ) -> list[ValidationOutcome]:
        """Worker 异步入口；HTTP 取消会传递到底层连接。"""

        async def invoke(errors: list[str] | None) -> dict[str, Any]:
            merged = _merge_repair_errors(repair_errors, errors)
            if isinstance(self.provider, HttpProvider):
                return await self.provider.analyze_event_impacts_async(
                    document_id=document_id,
                    security_id=security_id,
                    events=events,
                    repair_errors=merged,
                )
            return self.provider.analyze_event_impacts(
                document_id=document_id,
                security_id=security_id,
                events=events,
                repair_errors=merged,
            )

        aggregate = await self._validate_with_repair_async("event_impact_batch", invoke)
        return self._split_batch_outcomes(events, aggregate)

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

    async def extract_events_async(
        self,
        *,
        document_id: str,
        segments: list[tuple[str, str]],
        disclosure_time: str,
    ) -> ValidationOutcome:
        if isinstance(self.provider, HttpProvider):
            payload = await self.provider.extract_events_async(
                document_id=document_id,
                segments=segments,
                disclosure_time=disclosure_time,
            )
        else:
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

    def metric_recommend(
        self,
        *,
        security_id: str,
        hypothesis_id: str,
        hypothesis: str,
        industry: str,
        catalog_version: str,
        candidates: list[dict[str, Any]],
        top_k: int = 5,
        repair_errors: list[str] | None = None,
    ) -> ValidationOutcome:
        """让模型只能从受控指标目录的候选集合中选择。"""
        return self._validate_with_repair(
            "metric_recommend",
            lambda errors: self.provider.recommend_metrics(
                security_id=security_id,
                hypothesis_id=hypothesis_id,
                hypothesis=hypothesis,
                industry=industry,
                catalog_version=catalog_version,
                candidates=candidates,
                top_k=max(1, min(top_k, 20)),
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

    def hypothesis_quality(
        self,
        *,
        security_id: str,
        thesis_id: str,
        title: str,
        core_view: str,
        hypotheses: list[dict[str, Any]],
        repair_errors: list[str] | None = None,
    ) -> ValidationOutcome:
        return self._validate_with_repair(
            "hypothesis_quality",
            lambda errors: self.provider.hypothesis_quality(
                security_id=security_id,
                thesis_id=thesis_id,
                title=title,
                core_view=core_view,
                hypotheses=hypotheses,
                repair_errors=_merge_repair_errors(repair_errors, errors),
            ),
        )

    def logic_change_consolidation(
        self,
        *,
        security_id: str,
        thesis_id: str,
        business_date: str,
        thesis_core_view: str,
        hypotheses: list[dict[str, Any]],
        candidate_evidence: list[dict[str, Any]],
        repair_errors: list[str] | None = None,
    ) -> ValidationOutcome:
        """将同一公司同一主逻辑当日的候选证据收口为一条待确认变化。"""
        return self._validate_with_repair(
            "logic_change_consolidation",
            lambda errors: self.provider.consolidate_logic_change(
                security_id=security_id,
                thesis_id=thesis_id,
                business_date=business_date,
                thesis_core_view=thesis_core_view,
                hypotheses=hypotheses,
                candidate_evidence=candidate_evidence,
                repair_errors=_merge_repair_errors(repair_errors, errors),
            ),
        )

    async def logic_change_consolidation_async(
        self,
        *,
        security_id: str,
        thesis_id: str,
        business_date: str,
        thesis_core_view: str,
        hypotheses: list[dict[str, Any]],
        candidate_evidence: list[dict[str, Any]],
        repair_errors: list[str] | None = None,
    ) -> ValidationOutcome:
        async def invoke(errors: list[str] | None) -> dict[str, Any]:
            merged = _merge_repair_errors(repair_errors, errors)
            if isinstance(self.provider, HttpProvider):
                return await self.provider.consolidate_logic_change_async(
                    security_id=security_id,
                    thesis_id=thesis_id,
                    business_date=business_date,
                    thesis_core_view=thesis_core_view,
                    hypotheses=hypotheses,
                    candidate_evidence=candidate_evidence,
                    repair_errors=merged,
                )
            return self.provider.consolidate_logic_change(
                security_id=security_id,
                thesis_id=thesis_id,
                business_date=business_date,
                thesis_core_view=thesis_core_view,
                hypotheses=hypotheses,
                candidate_evidence=candidate_evidence,
                repair_errors=merged,
            )

        return await self._validate_with_repair_async("logic_change_consolidation", invoke)

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

    async def _validate_with_repair_async(
        self,
        schema_name: str,
        invoke: Callable[[list[str] | None], Awaitable[dict[str, Any]]],
    ) -> ValidationOutcome:
        outcome = validate(schema_name, await invoke(None), thresholds=self.settings.rules)
        if outcome.usable or not self.provider.supports_repair:
            return outcome
        repaired = validate(
            schema_name,
            await invoke(outcome.errors),
            thresholds=self.settings.rules,
            allow_repair=False,
        )
        return replace(repaired, repaired=repaired.usable)

    def _split_batch_outcomes(
        self, events: list[dict[str, Any]], aggregate: ValidationOutcome
    ) -> list[ValidationOutcome]:
        raw_results = aggregate.payload.get("results")
        by_id = (
            {
                str(item.get("event_id")): item.get("analysis")
                for item in raw_results
                if isinstance(item, dict)
            }
            if isinstance(raw_results, list)
            else {}
        )
        outcomes: list[ValidationOutcome] = []
        for item in events:
            event_id = str(item["event_id"])
            analysis = by_id.get(event_id)
            if aggregate.usable and isinstance(analysis, dict):
                outcomes.append(validate("event_impact", analysis, thresholds=self.settings.rules))
            else:
                outcomes.append(
                    ValidationOutcome(
                        ai_status=AiStatus.PARSE_FAILED,
                        payload=analysis if isinstance(analysis, dict) else {},
                        errors=[*aggregate.errors, f"批量结果缺少事件 {event_id}"],
                    )
                )
        return outcomes


def _merge_repair_errors(
    requested: list[str] | None, validation: list[str] | None
) -> list[str] | None:
    errors = [*(requested or ()), *(validation or ())]
    return errors or None
