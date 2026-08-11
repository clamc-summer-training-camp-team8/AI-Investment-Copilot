"""AI Agent 统一编排入口与运行状态。

该模块只负责 app/ai 内部编排和状态语义，不写数据库、不提交后端状态。
后端可以在外层为每次执行持久化 RuntimeExecution。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from app.core.enums import AiStatus

from app.ai.agent import (
    AgentEvent,
    AgentRunResult,
    CandidateHypothesis,
    EvidenceAgent,
    EvidenceGrade,
    EvidenceValidation,
    ThesisDraftAgent,
    ThesisDraftRunResult,
    InvestmentLogicChangeAgent,
)

RunStatus = Literal[
    "created",
    "retrieving",
    "generating",
    "verifying",
    "completed",
    "needs_human_review",
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
    errors: list[str] = field(default_factory=list)


class InvestmentResearchAgent:
    """把 AI 能力模块串起来，但不承担后端持久化职责。"""

    def __init__(self, *, thesis_draft: ThesisDraftAgent, logic_change: InvestmentLogicChangeAgent) -> None:
        self.thesis_draft = thesis_draft
        self.logic_change = logic_change

    def draft_thesis(self, **kwargs: Any) -> RuntimeExecution:
        execution = RuntimeExecution(run_id=f"run-{uuid4().hex[:12]}", task="thesis_draft")
        try:
            execution.status = "retrieving"
            execution.status = "generating"
            result: ThesisDraftRunResult = self.thesis_draft.generate(**kwargs)
            execution.result = result
            execution.status = ("needs_human_review" if result.outcome.ai_status is not AiStatus.CANDIDATE else "completed")
            if result.outcome.errors:
                execution.errors.extend(result.outcome.errors)
        except Exception as exc:  # noqa: BLE001 - 运行时边界统一转换为失败状态
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
        execution = RuntimeExecution(run_id=f"run-{uuid4().hex[:12]}", task="event_impact")
        try:
            execution.status = "retrieving"
            execution.status = "generating"
            result: AgentRunResult = self.logic_change.analyze(event, candidates, **kwargs)
            execution.result = result
            execution.status = "verifying"
            execution.evidence_checks = EvidenceAgent.validate_run(result)
            execution.evidence_grades = [EvidenceAgent.grade_impact(impact) for impact in result.impacts]
            has_review = any(check.requires_human_review for check in execution.evidence_checks) or any(not grade.passed for grade in execution.evidence_grades)
            execution.status = "needs_human_review" if has_review else "completed"
        except Exception as exc:  # noqa: BLE001 - 运行时边界统一转换为失败状态
            execution.status = "failed"
            execution.errors.append(str(exc))
        finally:
            execution.finished_at = _now()
        return execution
