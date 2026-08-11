"""AI Runtime 到后端的稳定、可 JSON 序列化交接格式。"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any

from app.ai.contracts.validator import load_schema
from app.ai.runtime import RuntimeExecution

BACKEND_ENVELOPE_VERSION = "ai-runtime-envelope-v1"


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    return value


def to_backend_envelope(execution: RuntimeExecution) -> dict[str, Any]:
    """序列化候选结果；不写库、不改变正式业务状态。"""
    schema_id = None
    if execution.schema_name:
        schema_id = load_schema(execution.schema_name).get("$id")
    retryable = execution.degraded_reason == "provider_or_schema_failure"
    return {
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
