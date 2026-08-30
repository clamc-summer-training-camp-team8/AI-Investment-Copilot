"""AI Runtime 到后端的稳定、可 JSON 序列化交接格式。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Literal

from app.ai.agents import AgentImpact, AgentRunResult, EvidenceAgent
from app.ai.contracts.validator import load_schema
from app.ai.runtime import RuntimeExecution
from app.core.enums import AiStatus, ImpactDirection

BACKEND_ENVELOPE_VERSION = "ai-runtime-envelope-v1"

ImpactValidationStatus = Literal["valid", "invalid"]


@dataclass(frozen=True)
class AgentImpactResult:
    """Agent 对单条候选假设的稳定后端交接结果。"""

    thesis_id: str
    hypothesis_id: str
    impact_direction: ImpactDirection
    strength_score: Decimal | None
    confidence: Decimal | None
    horizon: str | None
    rationale: str | None
    transmission_path: str | None
    citations: tuple[str, ...]
    ai_status: AiStatus
    validation_status: ImpactValidationStatus
    model_version: str | None
    prompt_version: str | None
    model_metadata: dict[str, object] | None


@dataclass(frozen=True)
class AgentAnalysisResult:
    """一次 Event 分析的稳定后端交接结果，保留全部候选假设判断。"""

    impacts: tuple[AgentImpactResult, ...]
    retryable: bool
    degraded_reason: str | None


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def to_backend_impact_result(impact: AgentImpact) -> AgentImpactResult:
    """把 Agent 内部 Impact 映射为稳定 DTO，不执行后端业务决策。"""
    payload = impact.outcome.payload
    signal = payload.get("signal")
    signal_data = signal if isinstance(signal, dict) else {}
    try:
        direction = ImpactDirection(
            str(signal_data.get("impact_direction") or ImpactDirection.NEUTRAL.value)
        )
    except ValueError:
        direction = ImpactDirection.NEUTRAL
    validation = EvidenceAgent.validate_impact(impact)
    metadata = payload.get("model_metadata")
    return AgentImpactResult(
        thesis_id=impact.candidate.thesis_id,
        hypothesis_id=impact.candidate.hypothesis_id,
        impact_direction=direction,
        strength_score=_optional_decimal(signal_data.get("strength")),
        confidence=_optional_decimal(signal_data.get("confidence")),
        horizon=_optional_text(signal_data.get("horizon")),
        rationale=_optional_text(signal_data.get("rationale")),
        transmission_path=_optional_text(signal_data.get("transmission_path")),
        citations=validation.cited_locators,
        ai_status=impact.outcome.ai_status,
        validation_status="valid" if validation.valid else "invalid",
        model_version=_optional_text(payload.get("model_version")),
        prompt_version=_optional_text(payload.get("prompt_version")),
        model_metadata=(metadata if isinstance(metadata, dict) else None),
    )


def to_backend_analysis_result(execution: RuntimeExecution) -> AgentAnalysisResult:
    """转换 Event Impact 执行结果；完整 RuntimeExecution 仍供 AiRun 审计。"""
    if execution.result is None:
        impacts: tuple[AgentImpactResult, ...] = ()
    elif isinstance(execution.result, AgentRunResult):
        impacts = tuple(to_backend_impact_result(impact) for impact in execution.result.impacts)
    else:
        raise TypeError("当前执行结果不是 AgentRunResult")
    return AgentAnalysisResult(
        impacts=impacts,
        retryable=execution.retryable,
        degraded_reason=execution.degraded_reason,
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_jsonable(item) for item in value]
    return value


def to_backend_envelope(execution: RuntimeExecution) -> dict[str, Any]:
    """序列化候选结果；不写库、不改变正式业务状态。"""
    schema_id = None
    if execution.schema_name:
        schema_id = load_schema(execution.schema_name).get("$id")
    retryable = execution.retryable or execution.degraded_reason == "provider_or_schema_failure"
    return {
        "idempotency_key": execution.idempotency_key,
        "attempt": execution.attempt,
        "transitions": _jsonable(execution.transitions),
        "model_calls": _jsonable(execution.model_calls),
        "envelope_version": BACKEND_ENVELOPE_VERSION,
        "run_id": execution.run_id,
        "task": execution.task,
        "status": execution.status,
        "started_at": execution.started_at.isoformat(),
        "finished_at": execution.finished_at.isoformat() if execution.finished_at else None,
        "requires_human_review": execution.status == "needs_human_review",
        "retryable": retryable,
        "degraded_reason": execution.degraded_reason,
        "errors": list(execution.errors),
        "versions": {
            "model": execution.model_version,
            "prompt": execution.prompt_version,
            "retrieval": list(execution.retrieval_versions),
            "schema_name": execution.schema_name,
            "schema_id": schema_id,
        },
        "candidate_result": _jsonable(execution.result),
        "verification": {
            "evidence_checks": _jsonable(execution.evidence_checks),
            "evidence_grades": _jsonable(execution.evidence_grades),
            "consistency_checks": _jsonable(execution.consistency_checks),
        },
    }
