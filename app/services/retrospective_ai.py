"""Source-grounded AI candidate generation for persisted retrospectives."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any
from uuid import uuid4

from app.ai.errors import ModelUnavailable
from app.ai.gateway import Gateway
from app.core.config import Settings
from app.core.domain import RetrospectiveRecord, UnitOfWork
from app.core.enums import AiStatus, RetrospectiveState
from app.core.timeutil import now
from app.services import audit, retrospective_query
from app.services.errors import ConcurrentUpdate, HumanGateRequired, ValidationFailed
from app.services.permission import Actor


@dataclass(frozen=True)
class _PreparedDraft:
    retrospective_id: str
    expected_lock_version: int
    run_id: str
    record: RetrospectiveRecord
    source_payload: list[dict[str, object]]
    hypotheses: list[dict[str, object]]
    allowed_source_ids: set[str]
    original_judgement: str
    scoped_settings: Settings


@dataclass(frozen=True)
class _GeneratedDraft:
    candidate: dict[str, object] | None
    errors: list[str]


def generate(
    uow: UnitOfWork,
    *,
    retrospective_id: str,
    expected_lock_version: int,
    actor: Actor,
    settings: Settings,
) -> dict[str, object]:
    """Generate in a caller-owned UoW, primarily for deterministic unit tests."""
    prepared = _prepare(
        uow,
        retrospective_id=retrospective_id,
        expected_lock_version=expected_lock_version,
        actor=actor,
        settings=settings,
    )
    generated = _call_model(prepared)
    return _persist(uow, prepared=prepared, generated=generated, actor=actor)


def generate_isolated(
    *,
    retrospective_id: str,
    expected_lock_version: int,
    actor: Actor,
    settings: Settings,
) -> dict[str, object]:
    """Run external AI outside database transactions.

    A short read transaction freezes a plain input value. The model call then runs
    without a checked-out database transaction, and a second short transaction saves
    the candidate only if the optimistic lock is still current.
    """
    from app.services.uow import uow_scope

    with uow_scope() as read_uow:
        prepared = _prepare(
            read_uow,
            retrospective_id=retrospective_id,
            expected_lock_version=expected_lock_version,
            actor=actor,
            settings=settings,
        )
    generated = _call_model(prepared)
    with uow_scope() as write_uow:
        return _persist(write_uow, prepared=prepared, generated=generated, actor=actor)


def _prepare(
    uow: UnitOfWork,
    *,
    retrospective_id: str,
    expected_lock_version: int,
    actor: Actor,
    settings: Settings,
) -> _PreparedDraft:
    if not settings.retrospective_ai_draft_enabled:
        raise ModelUnavailable("复盘 AI 草稿功能未启用", retryable=False)
    detail = retrospective_query.detail(uow, retrospective_id=retrospective_id, actor=actor)
    record, thesis = detail.record, detail.thesis
    if actor.user_id != record.owner:
        raise HumanGateRequired("只有复盘负责人可以生成 AI 候选")
    if expected_lock_version != record.lock_version:
        raise ConcurrentUpdate("复盘已被其他操作更新，请刷新后重试")
    if record.state in {
        RetrospectiveState.IN_REVIEW.value,
        RetrospectiveState.ARCHIVED.value,
    }:
        raise ValidationFailed("当前复盘状态不能生成 AI 候选")
    if (
        record.state == RetrospectiveState.PUBLISHED.value
        and not str(record.draft_content.get("revision_reason") or "").strip()
    ):
        raise ValidationFailed("已发布复盘需先创建修订草稿")

    sources = [
        item for item in detail.sources if item.metadata.get("availability") != "unavailable"
    ]
    if not sources:
        raise ValidationFailed("复盘没有冻结来源，不能生成 AI 候选")
    source_payload: list[dict[str, object]] = [
        {
            "source_id": item.source_id,
            "source_type": item.source_type,
            "summary": item.summary,
            "direction": item.direction,
            "strength": item.strength,
            "hypothesis_id": item.hypothesis_id,
            "disclosed_at": item.disclosed_at.isoformat() if item.disclosed_at else None,
            "confirmed_at": item.confirmed_at.isoformat() if item.confirmed_at else None,
        }
        for item in sources
    ]
    hypotheses: list[dict[str, object]] = [
        {
            "hypothesis_id": item.hypothesis_id,
            "statement": item.statement,
            "status": item.status,
        }
        for item in uow.thesis.list_hypotheses(record.thesis_id)
    ]
    scoped_settings = settings.model_copy(
        update={
            "llm_timeout_seconds": min(
                settings.llm_timeout_seconds,
                settings.retrospective_ai_timeout_seconds,
            ),
            "llm_analysis_timeout_seconds": settings.retrospective_ai_timeout_seconds,
        }
    )
    return _PreparedDraft(
        retrospective_id=retrospective_id,
        expected_lock_version=expected_lock_version,
        run_id=f"run-rtp-{uuid4().hex[:20]}",
        record=record,
        source_payload=source_payload,
        hypotheses=hypotheses,
        allowed_source_ids={item.source_id for item in sources},
        original_judgement=str(record.draft_content.get("original_judgement") or thesis.core_view),
        scoped_settings=scoped_settings,
    )


def _call_model(prepared: _PreparedDraft) -> _GeneratedDraft:
    record = prepared.record
    try:
        outcome = Gateway.build(prepared.scoped_settings).retrospective_draft(
            retrospective_id=prepared.retrospective_id,
            thesis_id=record.thesis_id,
            period_start=record.period_start.isoformat(),
            period_end=record.period_end.isoformat(),
            data_cutoff_at=record.data_cutoff_at.isoformat(),
            original_judgement=prepared.original_judgement,
            hypotheses=prepared.hypotheses,
            sources=prepared.source_payload,
        )
    except ModelUnavailable as exc:
        return _GeneratedDraft(candidate=None, errors=[str(exc)])
    if outcome.ai_status is AiStatus.PARSE_FAILED:
        return _GeneratedDraft(candidate=None, errors=list(outcome.errors))

    candidate = _clean(outcome.payload)
    try:
        _validate_candidate(candidate, prepared.allowed_source_ids)
    except ValidationFailed as exc:
        return _GeneratedDraft(candidate=None, errors=[str(exc)])
    return _GeneratedDraft(candidate=candidate, errors=list(outcome.errors))


def _persist(
    uow: UnitOfWork,
    *,
    prepared: _PreparedDraft,
    generated: _GeneratedDraft,
    actor: Actor,
) -> dict[str, object]:
    current, _ = retrospective_query.get_visible(
        uow, retrospective_id=prepared.retrospective_id, actor=actor
    )
    if current.owner != actor.user_id:
        raise HumanGateRequired("只有复盘负责人可以生成 AI 候选")
    if current.lock_version != prepared.expected_lock_version:
        raise ConcurrentUpdate("AI 生成期间复盘已被更新，候选未写入，请重新生成")
    if generated.candidate is None:
        failed = _store_failure(
            uow,
            record=current,
            run_id=prepared.run_id,
            expected_lock_version=prepared.expected_lock_version,
            actor=actor,
            error_count=max(1, len(generated.errors)),
        )
        return {
            "run_id": prepared.run_id,
            "status": "failed",
            "requires_human_review": True,
            "candidate": None,
            "errors": generated.errors,
            "lock_version": failed.lock_version,
        }

    candidate = generated.candidate
    updated = replace(
        current,
        ai_candidate=candidate,
        ai_run_id=prepared.run_id,
        ai_model_version=str(candidate.get("model_version") or "") or None,
        ai_prompt_version=str(candidate.get("prompt_version") or "") or None,
        ai_schema_version="retrospective_draft-v1",
        lock_version=current.lock_version + 1,
        updated_at=now(),
    )
    try:
        uow.retrospectives.update(updated, expected_lock_version=prepared.expected_lock_version)
    except RuntimeError as exc:
        if str(exc) == "retrospective_lock_conflict":
            raise ConcurrentUpdate("复盘已被其他操作更新，请刷新后重试") from exc
        raise
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action="生成复盘 AI 候选",
        object_type="retrospective",
        object_id=prepared.retrospective_id,
        detail={
            "run_id": prepared.run_id,
            "model_version": updated.ai_model_version,
            "prompt_version": updated.ai_prompt_version,
            "schema_version": updated.ai_schema_version,
            "source_count": len(prepared.allowed_source_ids),
            "source_fingerprint": current.source_fingerprint,
        },
    )
    return {
        "run_id": prepared.run_id,
        "status": "completed",
        "requires_human_review": True,
        "candidate": candidate,
        "errors": generated.errors,
        "lock_version": updated.lock_version,
    }


def _validate_candidate(candidate: dict[str, object], allowed_ids: set[str]) -> None:
    referenced: set[str] = set()
    citations = candidate.get("citations")
    if isinstance(citations, list):
        referenced.update(str(item) for item in citations)
    assessments = candidate.get("hypothesis_candidates")
    if isinstance(assessments, list):
        for item in assessments:
            if isinstance(item, dict) and isinstance(item.get("source_ids"), list):
                referenced.update(str(value) for value in item["source_ids"])
    balanced = candidate.get("balanced_evidence")
    if isinstance(balanced, dict):
        for key in ("supporting_source_ids", "conflicting_source_ids"):
            values = balanced.get(key)
            if isinstance(values, list):
                referenced.update(str(value) for value in values)
    unknown = referenced - allowed_ids
    if unknown:
        raise ValidationFailed("AI 候选引用了冻结来源白名单外的记录")
    raw = json.dumps(candidate, ensure_ascii=False, default=str).lower()
    if any(token in raw for token in ("<script", "<iframe", "javascript:", "data:text/html")):
        raise ValidationFailed("AI 候选包含不安全的 HTML 或脚本内容")


def _store_failure(
    uow: UnitOfWork,
    *,
    record: RetrospectiveRecord,
    run_id: str,
    expected_lock_version: int,
    actor: Actor,
    error_count: int,
) -> RetrospectiveRecord:
    updated = replace(
        record,
        ai_candidate={"status": "failed", "error_count": error_count},
        ai_run_id=run_id,
        ai_model_version=None,
        ai_prompt_version=None,
        ai_schema_version="retrospective_draft-v1",
        lock_version=record.lock_version + 1,
        updated_at=now(),
    )
    try:
        uow.retrospectives.update(updated, expected_lock_version=expected_lock_version)
    except RuntimeError as exc:
        if str(exc) == "retrospective_lock_conflict":
            raise ConcurrentUpdate("复盘已被其他操作更新，请刷新后重试") from exc
        raise
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action="复盘 AI 候选失败",
        object_type="retrospective",
        object_id=record.retrospective_id,
        detail={"run_id": run_id, "error_count": error_count},
    )
    return updated


def _clean(value: dict[str, Any]) -> dict[str, object]:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))
