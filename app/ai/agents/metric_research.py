"""假设—指标候选关联与阈值校准能力。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.ai.agents.types import MetricRecommendRunResult
from app.ai.contracts.validator import ValidationOutcome
from app.ai.gateway import Gateway
from app.ai.tools import (
    MetricCandidate,
    MetricCatalogTool,
    ThresholdMethod,
    ThresholdObservation,
    ThresholdReference,
    ThresholdSuggestion,
    ThresholdSuggestionTool,
)
from app.core.enums import AiStatus


class MetricResearchAgent:
    """先调用受控工具召回指标，再让模型在候选集合内给出关联建议。"""

    def __init__(
        self,
        *,
        gateway: Gateway,
        catalog: MetricCatalogTool | None = None,
        threshold_tool: ThresholdSuggestionTool | None = None,
    ) -> None:
        self.gateway = gateway
        self.catalog = catalog or MetricCatalogTool.from_seed()
        self.threshold_tool = threshold_tool or ThresholdSuggestionTool()

    def recommend(
        self,
        *,
        security_id: str,
        hypothesis_id: str,
        hypothesis: str,
        industry: str | None = None,
        top_k: int = 5,
    ) -> MetricRecommendRunResult:
        """召回可周期获得的规范指标，并请求模型给出候选关联。"""
        company = self.catalog.company_context(security_id)
        effective_industry = str(company["industry"]) if company else industry
        candidates = self.catalog.search(
            hypothesis=hypothesis,
            security_id=security_id,
            industry=effective_industry,
            top_k=max(top_k, 8),
        )
        outcome = self.gateway.metric_recommend(
            security_id=security_id,
            hypothesis_id=hypothesis_id,
            hypothesis=hypothesis,
            industry=effective_industry or "",
            catalog_version=self.catalog.catalog_version,
            candidates=[candidate.to_prompt_dict() for candidate in candidates],
            top_k=top_k,
        )
        outcome = _enforce_catalog_grounding(outcome, candidates=candidates, top_k=top_k)
        return MetricRecommendRunResult(
            security_id=security_id,
            hypothesis_id=hypothesis_id,
            catalog_version=self.catalog.catalog_version,
            candidates=tuple(candidates),
            outcome=outcome,
        )

    def suggest_threshold(
        self,
        *,
        observations: list[ThresholdObservation],
        expected_direction: str,
        as_of: date,
        method: ThresholdMethod = "auto",
        reference: ThresholdReference | None = None,
        quantile: Decimal = Decimal("0.25"),
        rounding_step: Decimal | None = None,
    ) -> ThresholdSuggestion:
        """调用确定性工具校准阈值；本方法不调用模型。"""
        return self.threshold_tool.suggest(
            observations=observations,
            expected_direction=expected_direction,
            as_of=as_of,
            method=method,
            reference=reference,
            quantile=quantile,
            rounding_step=rounding_step,
        )


def _enforce_catalog_grounding(
    outcome: ValidationOutcome,
    *,
    candidates: list[MetricCandidate],
    top_k: int,
) -> ValidationOutcome:
    """校验模型是否忠实复制候选目录字段，阻断编造或偷偷改写。"""
    if outcome.ai_status is AiStatus.PARSE_FAILED:
        return outcome
    allowed = {
        (item.metric_id, item.metric_version): item.to_prompt_dict() for item in candidates
    }
    recommendations = outcome.payload.get("recommendations")
    if not isinstance(recommendations, list):
        return outcome
    errors: list[str] = []
    if len(recommendations) > max(1, min(top_k, 20)):
        errors.append("推荐数量超过调用方允许的 top_k")
    copied_fields = (
        "metric_name",
        "relation_type",
        "expected_direction",
        "observation_frequency",
        "availability_grade",
        "threshold_policy",
    )
    for index, recommendation in enumerate(recommendations):
        if not isinstance(recommendation, dict):
            errors.append(f"recommendations[{index}] 不是对象")
            continue
        identity = (
            str(recommendation.get("metric_id") or ""),
            str(recommendation.get("metric_version") or ""),
        )
        candidate = allowed.get(identity)
        if candidate is None:
            errors.append(f"recommendations[{index}] 的指标不在受控候选集合中: {identity}")
            continue
        for field in copied_fields:
            if recommendation.get(field) != candidate.get(field):
                errors.append(f"recommendations[{index}].{field} 与目录不一致")
        if sorted(recommendation.get("source_ids") or []) != sorted(
            candidate.get("source_ids") or []
        ):
            errors.append(f"recommendations[{index}].source_ids 与目录不一致")
    if not errors:
        return outcome
    return ValidationOutcome(
        ai_status=AiStatus.PARSE_FAILED,
        payload=outcome.payload,
        errors=[*outcome.errors, *errors],
        repaired=outcome.repaired,
    )
