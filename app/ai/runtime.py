"""AI Agent 统一编排入口与运行状态。

该模块只负责 app/ai 内部编排和状态语义，不写数据库、不提交后端状态。
后端可以在外层为每次执行持久化 RuntimeExecution。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any, Literal
from uuid import uuid4

from app.ai.agents import (
    AgentEventInput,
    AgentRunResult,
    EvidenceAgent,
    EvidenceConsistency,
    EvidenceGrade,
    EvidenceValidation,
    HypothesisInput,
    InvestmentLogicChangeAgent,
    MetricExplainAgent,
    MetricExplainRunResult,
    MetricRecommendRunResult,
    MetricResearchAgent,
    ReviewAgent,
    ReviewDraftRunResult,
    ThesisDraftAgent,
    ThesisDraftRunResult,
)
from app.ai.errors import ModelUnavailable
from app.ai.gateway import Gateway
from app.ai.observability import (
    ModelCallUsage,
    NullRuntimeRecorder,
    RuntimeRecorder,
    usage_from_payload,
)
from app.ai.retrieval import KeywordRetriever, RetrievalDocument, Retriever
from app.ai.tools import (
    ThresholdMethod,
    ThresholdObservation,
    ThresholdReference,
    ThresholdSuggestion,
)
from app.core.enums import AiStatus

RunStatus = Literal[
    "created",
    "retrieving",
    "generating",
    "verifying",
    "completed",
    "needs_human_review",
    "degraded",
    "failed",
]


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class RunTransition:
    status: RunStatus
    occurred_at: datetime


@dataclass
class RuntimeExecution:
    run_id: str
    task: str
    status: RunStatus = "created"
    started_at: datetime = field(default_factory=_now)
    finished_at: datetime | None = None
    result: Any = None
    evidence_checks: list[EvidenceValidation] = field(default_factory=list)
    evidence_grades: list[EvidenceGrade] = field(default_factory=list)
    consistency_checks: list[EvidenceConsistency] = field(default_factory=list)
    model_version: str | None = None
    prompt_version: str | None = None
    retrieval_versions: tuple[str, ...] = ()
    schema_name: str | None = None
    degraded_reason: str | None = None
    errors: list[str] = field(default_factory=list)
    transitions: list[RunTransition] = field(default_factory=list)
    model_calls: list[ModelCallUsage] = field(default_factory=list)
    retryable: bool = False
    idempotency_key: str | None = None
    attempt: int = 1


def _payload_versions(execution: RuntimeExecution, payloads: list[dict[str, Any]]) -> None:
    model_versions = {str(item["model_version"]) for item in payloads if item.get("model_version")}
    prompt_versions = {
        str(item["prompt_version"]) for item in payloads if item.get("prompt_version")
    }
    execution.model_version = ",".join(sorted(model_versions)) or None
    execution.prompt_version = ",".join(sorted(prompt_versions)) or None


class InvestmentResearchAgent:
    """把 AI 能力模块串起来，但不承担后端持久化职责。"""

    def __init__(
        self,
        *,
        thesis_draft: ThesisDraftAgent,
        logic_change: InvestmentLogicChangeAgent,
        metric_explain: MetricExplainAgent | None = None,
        metric_research: MetricResearchAgent | None = None,
        review: ReviewAgent | None = None,
        recorder: RuntimeRecorder | None = None,
    ) -> None:
        self.thesis_draft = thesis_draft
        self.logic_change = logic_change
        self.metric_explain = metric_explain or MetricExplainAgent(gateway=thesis_draft.gateway)
        self.metric_research = metric_research or MetricResearchAgent(gateway=thesis_draft.gateway)
        self.review = review or ReviewAgent(gateway=thesis_draft.gateway)
        self.recorder = recorder or NullRuntimeRecorder()

    @classmethod
    def build(
        cls,
        gateway: Gateway,
        retriever: Retriever | None = None,
        recorder: RuntimeRecorder | None = None,
    ) -> InvestmentResearchAgent:
        """从稳定的 Gateway 与 Retriever 接口构造完整编排器。"""
        active_retriever = retriever or KeywordRetriever()
        return cls(
            thesis_draft=ThesisDraftAgent(gateway=gateway, retriever=active_retriever),
            logic_change=InvestmentLogicChangeAgent(
                gateway=gateway,
                retriever=active_retriever,
            ),
            recorder=recorder,
        )

    def _new_execution(
        self,
        *,
        task: str,
        schema_name: str,
        idempotency_key: str | None,
        attempt: int,
    ) -> RuntimeExecution:
        run_id = (
            f"run-{sha256(f'{task}:{idempotency_key}'.encode()).hexdigest()[:20]}"
            if idempotency_key
            else f"run-{uuid4().hex[:20]}"
        )
        execution = RuntimeExecution(
            run_id=run_id,
            task=task,
            schema_name=schema_name,
            idempotency_key=idempotency_key,
            attempt=max(attempt, 1),
        )
        execution.transitions.append(RunTransition("created", execution.started_at))
        self.recorder.started(execution)
        return execution

    def _transition(self, execution: RuntimeExecution, status: RunStatus) -> None:
        execution.status = status
        execution.transitions.append(RunTransition(status, _now()))
        self.recorder.checkpoint(execution)

    def _record_payloads(
        self,
        execution: RuntimeExecution,
        payloads: list[dict[str, Any]],
    ) -> None:
        _payload_versions(execution, payloads)
        execution.model_calls.extend(
            usage_from_payload(payload, self.thesis_draft.gateway.settings) for payload in payloads
        )

    def _finish(self, execution: RuntimeExecution) -> None:
        execution.finished_at = _now()
        self.recorder.finished(execution)

    def draft_thesis(
        self,
        *,
        security_id: str,
        view: str = "",
        source_document_id: str | None = None,
        source_segments: list[RetrievalDocument] | None = None,
        investment_context: dict[str, Any] | None = None,
        industry_metrics: list[dict[str, Any]] | None = None,
        as_of: datetime | None = None,
        allowed_visibility: frozenset[str] = frozenset({"公开"}),
        top_k: int = 8,
        idempotency_key: str | None = None,
        attempt: int = 1,
    ) -> RuntimeExecution:
        execution = self._new_execution(
            task="thesis_draft",
            schema_name="thesis_draft",
            idempotency_key=idempotency_key,
            attempt=attempt,
        )
        try:
            self._transition(execution, "retrieving")
            self._transition(execution, "generating")
            result: ThesisDraftRunResult = self.thesis_draft.generate(
                security_id=security_id,
                view=view,
                source_document_id=source_document_id,
                source_segments=source_segments,
                investment_context=investment_context,
                industry_metrics=industry_metrics,
                as_of=as_of,
                allowed_visibility=allowed_visibility,
                top_k=top_k,
            )
            execution.result = result
            execution.retrieval_versions = (result.retrieval.retrieval_version,)
            self._record_payloads(execution, [result.outcome.payload])
            if result.outcome.errors:
                execution.errors.extend(result.outcome.errors)
            if result.outcome.ai_status is AiStatus.PARSE_FAILED:
                execution.retryable = True
                execution.degraded_reason = "provider_or_schema_failure"
                self._transition(execution, "degraded")
            elif result.outcome.ai_status is AiStatus.LOW_CONFIDENCE:
                self._transition(execution, "needs_human_review")
            else:
                self._transition(execution, "completed")
        except ModelUnavailable as exc:
            execution.retryable = exc.retryable
            execution.degraded_reason = "model_unavailable"
            execution.errors.append(str(exc))
            self._transition(execution, "degraded")
        except Exception as exc:
            execution.degraded_reason = "unexpected_runtime_failure"
            execution.errors.append(str(exc))
            self._transition(execution, "failed")
        finally:
            self._finish(execution)
        return execution

    def analyze_event(
        self,
        event: AgentEventInput,
        hypotheses: tuple[HypothesisInput, ...],
        *,
        allowed_visibility: frozenset[str] = frozenset({"公开"}),
        top_k: int = 3,
        idempotency_key: str | None = None,
        attempt: int = 1,
    ) -> RuntimeExecution:
        execution = self._new_execution(
            task="event_impact",
            schema_name="event_impact",
            idempotency_key=idempotency_key,
            attempt=attempt,
        )
        try:
            self._transition(execution, "retrieving")
            self._transition(execution, "generating")
            result: AgentRunResult = self.logic_change.analyze(
                event,
                hypotheses,
                allowed_visibility=allowed_visibility,
                top_k=top_k,
            )
            execution.result = result
            execution.retrieval_versions = tuple(
                sorted({impact.retrieval.retrieval_version for impact in result.impacts})
            )
            self._record_payloads(
                execution,
                [result.impacts[0].outcome.payload] if result.impacts else [],
            )
            for impact in result.impacts:
                for error in impact.outcome.errors:
                    if error not in execution.errors:
                        execution.errors.append(error)
            self._transition(execution, "verifying")
            execution.evidence_checks = EvidenceAgent.validate_run(result)
            execution.evidence_grades = [
                EvidenceAgent.grade_impact(impact) for impact in result.impacts
            ]
            execution.consistency_checks = [
                EvidenceAgent.check_consistency(impact) for impact in result.impacts
            ]
            if any(impact.outcome.ai_status is AiStatus.PARSE_FAILED for impact in result.impacts):
                execution.retryable = True
                execution.degraded_reason = "provider_or_schema_failure"
                self._transition(execution, "degraded")
            else:
                has_review = (
                    any(check.requires_human_review for check in execution.evidence_checks)
                    or any(not grade.passed for grade in execution.evidence_grades)
                    or any(check.reasons for check in execution.consistency_checks)
                    or any(
                        impact.outcome.ai_status is AiStatus.LOW_CONFIDENCE
                        for impact in result.impacts
                    )
                )
                self._transition(
                    execution,
                    "needs_human_review" if has_review else "completed",
                )
        except ModelUnavailable as exc:
            execution.retryable = exc.retryable
            execution.degraded_reason = "model_unavailable"
            execution.errors.append(str(exc))
            self._transition(execution, "degraded")
        except Exception as exc:
            execution.degraded_reason = "unexpected_runtime_failure"
            execution.errors.append(str(exc))
            self._transition(execution, "failed")
        finally:
            self._finish(execution)
        return execution

    def analyze_events(
        self,
        events: tuple[AgentEventInput, ...],
        hypotheses: tuple[HypothesisInput, ...],
        *,
        allowed_visibility: frozenset[str] = frozenset({"公开"}),
        top_k: int = 3,
        idempotency_key: str | None = None,
    ) -> list[RuntimeExecution]:
        """用一个模型调用生成多个事件结果，并保留逐事件运行记录。"""
        executions = [
            self._new_execution(
                task="event_impact_batch",
                schema_name="event_impact",
                idempotency_key=f"{idempotency_key}:{event.event_id}" if idempotency_key else None,
                attempt=1,
            )
            for event in events
        ]
        try:
            for execution in executions:
                self._transition(execution, "retrieving")
                self._transition(execution, "generating")
            results = self.logic_change.analyze_many(
                events,
                hypotheses,
                allowed_visibility=allowed_visibility,
                top_k=top_k,
            )
            for execution, result in zip(executions, results, strict=True):
                execution.result = result
                execution.retrieval_versions = tuple(
                    sorted({impact.retrieval.retrieval_version for impact in result.impacts})
                )
                self._record_payloads(execution, [result.impacts[0].outcome.payload] if result.impacts else [])
                self._transition(execution, "verifying")
                execution.evidence_checks = EvidenceAgent.validate_run(result)
                execution.evidence_grades = [EvidenceAgent.grade_impact(item) for item in result.impacts]
                execution.consistency_checks = [EvidenceAgent.check_consistency(item) for item in result.impacts]
                if any(item.outcome.ai_status is AiStatus.PARSE_FAILED for item in result.impacts):
                    execution.retryable = False
                    execution.degraded_reason = "provider_or_schema_failure"
                    self._transition(execution, "degraded")
                else:
                    self._transition(execution, "needs_human_review")
        except ModelUnavailable as exc:
            for execution in executions:
                execution.retryable = False
                execution.degraded_reason = "model_unavailable"
                execution.errors.append(str(exc))
                self._transition(execution, "degraded")
        except Exception as exc:
            for execution in executions:
                execution.degraded_reason = "unexpected_runtime_failure"
                execution.errors.append(str(exc))
                self._transition(execution, "failed")
        finally:
            for execution in executions:
                self._finish(execution)
        return executions

    async def analyze_events_async(
        self,
        events: tuple[AgentEventInput, ...],
        hypotheses: tuple[HypothesisInput, ...],
        *,
        allowed_visibility: frozenset[str] = frozenset({"公开"}),
        top_k: int = 3,
        idempotency_key: str | None = None,
    ) -> list[RuntimeExecution]:
        """异步批量影响分析，允许 worker 超时取消远程请求。"""
        executions = [
            self._new_execution(
                task="event_impact_batch",
                schema_name="event_impact",
                idempotency_key=f"{idempotency_key}:{event.event_id}" if idempotency_key else None,
                attempt=1,
            )
            for event in events
        ]
        try:
            for execution in executions:
                self._transition(execution, "retrieving")
                self._transition(execution, "generating")
            results = await self.logic_change.analyze_many_async(
                events,
                hypotheses,
                allowed_visibility=allowed_visibility,
                top_k=top_k,
            )
            for execution, result in zip(executions, results, strict=True):
                execution.result = result
                execution.retrieval_versions = tuple(
                    sorted({impact.retrieval.retrieval_version for impact in result.impacts})
                )
                self._record_payloads(
                    execution, [result.impacts[0].outcome.payload] if result.impacts else []
                )
                self._transition(execution, "verifying")
                execution.evidence_checks = EvidenceAgent.validate_run(result)
                execution.evidence_grades = [
                    EvidenceAgent.grade_impact(item) for item in result.impacts
                ]
                execution.consistency_checks = [
                    EvidenceAgent.check_consistency(item) for item in result.impacts
                ]
                if any(
                    item.outcome.ai_status is AiStatus.PARSE_FAILED for item in result.impacts
                ):
                    execution.retryable = False
                    execution.degraded_reason = "provider_or_schema_failure"
                    self._transition(execution, "degraded")
                else:
                    self._transition(execution, "needs_human_review")
        except ModelUnavailable as exc:
            for execution in executions:
                execution.retryable = False
                execution.degraded_reason = "model_unavailable"
                execution.errors.append(str(exc))
                self._transition(execution, "degraded")
        except Exception as exc:
            for execution in executions:
                execution.degraded_reason = "unexpected_runtime_failure"
                execution.errors.append(str(exc))
                self._transition(execution, "failed")
        finally:
            for execution in executions:
                self._finish(execution)
        return executions

    def explain_metric(
        self,
        *,
        security_id: str,
        hypothesis_id: str,
        hypothesis: str,
        calc_result: dict[str, object],
        idempotency_key: str | None = None,
        attempt: int = 1,
    ) -> RuntimeExecution:
        execution = self._new_execution(
            task="metric_explain",
            schema_name="metric_explain",
            idempotency_key=idempotency_key,
            attempt=attempt,
        )
        try:
            self._transition(execution, "generating")
            result: MetricExplainRunResult = self.metric_explain.explain(
                security_id=security_id,
                hypothesis_id=hypothesis_id,
                hypothesis=hypothesis,
                calc_result=calc_result,
            )
            execution.result = result
            self._record_payloads(execution, [result.outcome.payload])
            execution.errors.extend(result.outcome.errors)
            if result.outcome.ai_status is AiStatus.PARSE_FAILED:
                execution.retryable = True
                execution.degraded_reason = "provider_or_schema_failure"
                self._transition(execution, "degraded")
            elif result.outcome.ai_status is AiStatus.LOW_CONFIDENCE:
                self._transition(execution, "needs_human_review")
            else:
                self._transition(execution, "completed")
        except ModelUnavailable as exc:
            execution.retryable = exc.retryable
            execution.degraded_reason = "model_unavailable"
            execution.errors.append(str(exc))
            self._transition(execution, "degraded")
        except Exception as exc:
            execution.degraded_reason = "unexpected_runtime_failure"
            execution.errors.append(str(exc))
            self._transition(execution, "failed")
        finally:
            self._finish(execution)
        return execution

    def recommend_metrics(
        self,
        *,
        security_id: str,
        hypothesis_id: str,
        hypothesis: str,
        industry: str | None = None,
        top_k: int = 5,
        idempotency_key: str | None = None,
        attempt: int = 1,
    ) -> RuntimeExecution:
        """向后端提供统一的假设—指标推荐执行入口。"""
        execution = self._new_execution(
            task="metric_recommend",
            schema_name="metric_recommend",
            idempotency_key=idempotency_key,
            attempt=attempt,
        )
        try:
            self._transition(execution, "retrieving")
            self._transition(execution, "generating")
            result: MetricRecommendRunResult = self.metric_research.recommend(
                security_id=security_id,
                hypothesis_id=hypothesis_id,
                hypothesis=hypothesis,
                industry=industry,
                top_k=top_k,
            )
            execution.result = result
            execution.retrieval_versions = (result.catalog_version,)
            self._record_payloads(execution, [result.outcome.payload])
            execution.errors.extend(result.outcome.errors)
            if result.outcome.ai_status is AiStatus.PARSE_FAILED:
                execution.retryable = True
                execution.degraded_reason = "provider_or_schema_failure"
                self._transition(execution, "degraded")
            elif result.outcome.ai_status is AiStatus.LOW_CONFIDENCE:
                self._transition(execution, "needs_human_review")
            else:
                self._transition(execution, "completed")
        except ModelUnavailable as exc:
            execution.retryable = exc.retryable
            execution.degraded_reason = "model_unavailable"
            execution.errors.append(str(exc))
            self._transition(execution, "degraded")
        except Exception as exc:
            execution.degraded_reason = "unexpected_runtime_failure"
            execution.errors.append(str(exc))
            self._transition(execution, "failed")
        finally:
            self._finish(execution)
        return execution

    def suggest_metric_threshold(
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
        """向后端暴露确定性阈值校准；该入口不调用模型，也不写正式规则。"""
        return self.metric_research.suggest_threshold(
            observations=observations,
            expected_direction=expected_direction,
            as_of=as_of,
            method=method,
            reference=reference,
            quantile=quantile,
            rounding_step=rounding_step,
        )

    def draft_review(
        self,
        *,
        security_id: str,
        thesis_id: str,
        period_start: date,
        period_end: date,
        records: list[dict[str, object]],
        idempotency_key: str | None = None,
        attempt: int = 1,
    ) -> RuntimeExecution:
        execution = self._new_execution(
            task="review_draft",
            schema_name="review_draft",
            idempotency_key=idempotency_key,
            attempt=attempt,
        )
        try:
            self._transition(execution, "generating")
            result: ReviewDraftRunResult = self.review.generate(
                security_id=security_id,
                thesis_id=thesis_id,
                period_start=period_start,
                period_end=period_end,
                records=records,
            )
            execution.result = result
            self._record_payloads(execution, [result.outcome.payload])
            execution.errors.extend(result.outcome.errors)
            if result.outcome.ai_status is AiStatus.PARSE_FAILED:
                execution.retryable = True
                execution.degraded_reason = "provider_or_schema_failure"
                self._transition(execution, "degraded")
            else:
                self._transition(execution, "needs_human_review")
        except ModelUnavailable as exc:
            execution.retryable = exc.retryable
            execution.degraded_reason = "model_unavailable"
            execution.errors.append(str(exc))
            self._transition(execution, "degraded")
        except Exception as exc:
            execution.degraded_reason = "unexpected_runtime_failure"
            execution.errors.append(str(exc))
            self._transition(execution, "failed")
        finally:
            self._finish(execution)
        return execution
