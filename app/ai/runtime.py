"""AI Agent 统一编排入口与运行状态。

该模块只负责 app/ai 内部编排和状态语义，不写数据库、不提交后端状态。
后端可以在外层为每次执行持久化 RuntimeExecution。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from app.ai.agent import (
    AgentEvent,
    AgentRunResult,
    CandidateHypothesis,
    EvidenceAgent,
    EvidenceConsistency,
    EvidenceGrade,
    EvidenceValidation,
    InvestmentLogicChangeAgent,
    MetricExplainAgent,
    MetricExplainRunResult,
    ReviewAgent,
    ReviewDraftRunResult,
    ThesisDraftAgent,
    ThesisDraftRunResult,
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
    return datetime.now(timezone.utc)


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


def _payload_versions(execution: RuntimeExecution, payloads: list[dict[str, Any]]) -> None:
    model_versions = {str(item["model_version"]) for item in payloads if item.get("model_version")}
    prompt_versions = {str(item["prompt_version"]) for item in payloads if item.get("prompt_version")}
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
        review: ReviewAgent | None = None,
    ) -> None:
        self.thesis_draft = thesis_draft
        self.logic_change = logic_change
        self.metric_explain = metric_explain or MetricExplainAgent(gateway=thesis_draft.gateway)
        self.review = review or ReviewAgent(gateway=thesis_draft.gateway)

    def draft_thesis(self, **kwargs: Any) -> RuntimeExecution:
        execution = RuntimeExecution(
            run_id=f"run-{uuid4().hex[:12]}",
            task="thesis_draft",
            schema_name="thesis_draft",
        )
        try:
            execution.status = "retrieving"
            execution.status = "generating"
            result: ThesisDraftRunResult = self.thesis_draft.generate(**kwargs)
            execution.result = result
            execution.retrieval_versions = (result.retrieval.retrieval_version,)
            _payload_versions(execution, [result.outcome.payload])
            if result.outcome.errors:
                execution.errors.extend(result.outcome.errors)
            if result.outcome.ai_status is AiStatus.PARSE_FAILED:
                execution.status = "degraded"
                execution.degraded_reason = "provider_or_schema_failure"
            elif result.outcome.ai_status is AiStatus.LOW_CONFIDENCE:
                execution.status = "needs_human_review"
            else:
                execution.status = "completed"
        except Exception as exc:  # noqa: BLE001 - 非预期编程/配置异常统一为 failed
            execution.status = "failed"
            execution.errors.append(str(exc))
        finally:
            execution.finished_at = _now()
        return execution

    def analyze_event(
        self,
        event: AgentEvent,
        candidates: list[CandidateHypothesis],
        **kwargs: Any,
    ) -> RuntimeExecution:
        execution = RuntimeExecution(
            run_id=f"run-{uuid4().hex[:12]}",
            task="event_impact",
            schema_name="event_impact",
        )
        try:
            if not candidates:
                execution.status = "degraded"
                execution.degraded_reason = "no_candidate_hypotheses"
                execution.errors.append("没有可分析的候选假设，需先召回或人工选择假设")
                return execution
            execution.status = "retrieving"
            execution.status = "generating"
            result: AgentRunResult = self.logic_change.analyze(event, candidates, **kwargs)
            execution.result = result
            execution.retrieval_versions = tuple(
                sorted({impact.retrieval.retrieval_version for impact in result.impacts})
            )
            _payload_versions(execution, [impact.outcome.payload for impact in result.impacts])
            for impact in result.impacts:
                execution.errors.extend(impact.outcome.errors)
            execution.status = "verifying"
            execution.evidence_checks = EvidenceAgent.validate_run(result)
            execution.evidence_grades = [EvidenceAgent.grade_impact(impact) for impact in result.impacts]
            execution.consistency_checks = [
                EvidenceAgent.check_consistency(impact) for impact in result.impacts
            ]
            if any(
                impact.outcome.ai_status is AiStatus.PARSE_FAILED for impact in result.impacts
            ):
                execution.status = "degraded"
                execution.degraded_reason = "provider_or_schema_failure"
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
                execution.status = "needs_human_review" if has_review else "completed"
        except Exception as exc:  # noqa: BLE001 - 非预期编程/配置异常统一为 failed
            execution.status = "failed"
            execution.errors.append(str(exc))
        finally:
            execution.finished_at = _now()
        return execution
    def explain_metric(self, **kwargs: Any) -> RuntimeExecution:
        execution = RuntimeExecution(
            run_id=f"run-{uuid4().hex[:12]}",
            task="metric_explain",
            schema_name="metric_explain",
        )
        try:
            execution.status = "generating"
            result: MetricExplainRunResult = self.metric_explain.explain(**kwargs)
            execution.result = result
            _payload_versions(execution, [result.outcome.payload])
            execution.errors.extend(result.outcome.errors)
            if result.outcome.ai_status is AiStatus.PARSE_FAILED:
                execution.status = "degraded"
                execution.degraded_reason = "provider_or_schema_failure"
            elif result.outcome.ai_status is AiStatus.LOW_CONFIDENCE:
                execution.status = "needs_human_review"
            else:
                execution.status = "completed"
        except Exception as exc:  # noqa: BLE001 - 非预期编程/配置异常统一为 failed
            execution.status = "failed"
            execution.errors.append(str(exc))
        finally:
            execution.finished_at = _now()
        return execution

    def draft_review(self, **kwargs: Any) -> RuntimeExecution:
        execution = RuntimeExecution(
            run_id=f"run-{uuid4().hex[:12]}",
            task="review_draft",
            schema_name="review_draft",
        )
        try:
            execution.status = "generating"
            result: ReviewDraftRunResult = self.review.generate(**kwargs)
            execution.result = result
            _payload_versions(execution, [result.outcome.payload])
            execution.errors.extend(result.outcome.errors)
            if result.outcome.ai_status is AiStatus.PARSE_FAILED:
                execution.status = "degraded"
                execution.degraded_reason = "provider_or_schema_failure"
            else:
                execution.status = "needs_human_review"
        except Exception as exc:  # noqa: BLE001 - 非预期编程/配置异常统一为 failed
            execution.status = "failed"
            execution.errors.append(str(exc))
        finally:
            execution.finished_at = _now()
        return execution