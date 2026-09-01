"""Point-in-time, permission-aware source snapshots for retrospectives."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any

from app.core.config import Settings
from app.core.domain import (
    HypothesisRecord,
    RetrospectiveSourceRecord,
    ThesisRecord,
    UnitOfWork,
)
from app.core.enums import (
    ConfirmationStatus,
    DocumentContentStatus,
    SourceAuthorizationStatus,
)
from app.core.timeutil import now
from app.services import permission
from app.services.errors import NotVisible, ValidationFailed
from app.services.permission import Actor


@dataclass(frozen=True)
class SourcePreview:
    thesis: ThesisRecord
    hypotheses: tuple[HypothesisRecord, ...]
    sources: tuple[RetrospectiveSourceRecord, ...]
    source_fingerprint: str
    completeness_completed: int
    completeness_applicable: int
    completeness_score: Decimal
    missing_items: tuple[str, ...]
    excluded_counts: dict[str, int]


def build_preview(
    uow: UnitOfWork,
    *,
    thesis_id: str,
    period_start: date,
    period_end: date,
    data_cutoff_at: datetime,
    actor: Actor,
    settings: Settings,
    retrospective_id: str = "preview",
) -> SourcePreview:
    if period_end < period_start:
        raise ValidationFailed("复盘结束日期不能早于开始日期")
    if data_cutoff_at.tzinfo is None:
        raise ValidationFailed("复盘数据截止时点必须带时区")
    if data_cutoff_at.date() < period_end:
        raise ValidationFailed("复盘数据截止时点不能早于复盘结束日期")
    if data_cutoff_at > now():
        raise ValidationFailed("复盘数据截止时点不能晚于当前时间")

    thesis = uow.thesis.get(thesis_id)
    if thesis is None:
        raise NotVisible("逻辑不存在或无访问权限")
    permission.ensure_thesis_visible(
        actor,
        thesis_id=thesis_id,
        owner=thesis.owner,
        visibility=thesis.visibility,
        team=thesis.team,
    )
    hypotheses = tuple(uow.thesis.list_hypotheses(thesis_id))
    sources: list[RetrospectiveSourceRecord] = []
    excluded = {
        "pending_or_rejected_relation": 0,
        "future_record": 0,
        "title_index_or_unparsed": 0,
        "missing_or_invisible_document": 0,
    }
    missing: list[str] = []

    all_versions = uow.versions.list_for_thesis(thesis_id)
    versions = [
        item
        for item in all_versions
        if item.created_at is not None and item.created_at <= data_cutoff_at
    ]
    excluded["future_record"] += len(all_versions) - len(versions)
    versions.sort(key=lambda item: item.version)
    baseline_versions = [
        item
        for item in versions
        if item.created_at is not None and item.created_at.date() <= period_start
    ]
    baseline = baseline_versions[-1] if baseline_versions else None
    endpoint = versions[-1] if versions else None
    selected_versions = ([baseline] if baseline is not None else []) + [
        item
        for item in versions
        if item.created_at is not None and item.created_at.date() > period_start
    ]
    selected_versions = list({item.version: item for item in selected_versions}.values())
    selected_versions.sort(key=lambda item: item.version)
    for item in selected_versions:
        sources.append(
            _source(
                retrospective_id,
                source_type="thesis_version",
                object_id=thesis_id,
                object_version=str(item.version),
                summary=(
                    f"V{item.version} · {item.triggered_by}"
                    + (f" · {item.change_reason}" if item.change_reason else "")
                ),
                disclosed_at=item.created_at,
                metadata={
                    "version": item.version,
                    "triggered_by": item.triggered_by,
                    "created_by": item.created_by,
                    "change_reason": item.change_reason,
                    "changed_fields": list(item.changed_fields),
                    "data_cutoff_at": _iso(item.data_cutoff_at),
                    "snapshot": item.snapshot,
                },
            )
        )

    relations = uow.relations.list_for_thesis(thesis_id)
    confirmed_evidence_count = 0
    traced_evidence_count = 0
    for relation in relations:
        if relation.status is not ConfirmationStatus.CONFIRMED:
            excluded["pending_or_rejected_relation"] += 1
            continue
        if relation.reviewed_at is None or relation.reviewed_at > data_cutoff_at:
            excluded["future_record"] += 1
            continue
        evidence = uow.evidence.get(relation.evidence_id)
        if evidence is None:
            excluded["missing_or_invisible_document"] += 1
            continue
        if evidence.disclosed_at is None or evidence.disclosed_at > data_cutoff_at:
            excluded["future_record"] += 1
            continue
        if evidence.ingested_at is not None and evidence.ingested_at > data_cutoff_at:
            excluded["future_record"] += 1
            continue
        confirmed_evidence_count += 1
        if not permission.can_read_document(
            actor, visibility_label=evidence.source_visibility_label
        ):
            excluded["missing_or_invisible_document"] += 1
            continue
        document = (
            uow.documents.get(evidence.source_document_id) if evidence.source_document_id else None
        )
        if document is None or document.deleted_at is not None:
            excluded["missing_or_invisible_document"] += 1
            continue
        if not permission.can_read_document(actor, visibility_label=document.visibility_label):
            excluded["missing_or_invisible_document"] += 1
            continue
        if document.content_status not in {
            DocumentContentStatus.FULL_TEXT.value,
            DocumentContentStatus.SYNTHETIC.value,
        }:
            excluded["title_index_or_unparsed"] += 1
            continue
        locator = evidence.evidence_locator.strip()
        if not locator:
            missing.append(f"证据 {evidence.evidence_id} 缺少原文 locator")
            continue
        revisions = uow.assets.list_document_revisions(document.document_id)
        revision = next(
            (
                item
                for item in revisions
                if item.object_key is not None
                and item.tombstoned_at is None
                and item.created_at is not None
                and item.created_at <= data_cutoff_at
            ),
            None,
        )
        if revisions and revision is None:
            excluded["future_record"] += 1
            continue
        if revision is not None and revision.authorization_status in {
            SourceAuthorizationStatus.PENDING.value,
            SourceAuthorizationStatus.RESTRICTED.value,
        }:
            excluded["missing_or_invisible_document"] += 1
            continue
        traced_evidence_count += 1
        sources.append(
            _source(
                retrospective_id,
                source_type="confirmed_evidence",
                object_id=relation.relation_id,
                object_version=revision.revision_id if revision else document.parser_version,
                locator=locator,
                content_hash=revision.content_hash if revision else document.content_hash,
                summary=(evidence.fact_excerpt or evidence.source_document_title or "已确认证据")[
                    :1000
                ],
                direction=relation.direction.value,
                strength=relation.strength,
                hypothesis_id=relation.hypothesis_id,
                disclosed_at=evidence.disclosed_at,
                confirmed_at=relation.reviewed_at,
                visibility_label=document.visibility_label,
                metadata={
                    "evidence_id": evidence.evidence_id,
                    "relation_id": relation.relation_id,
                    "document_id": document.document_id,
                    "document_title": document.title,
                    "reviewed_by": relation.reviewed_by,
                    "reason": relation.reason,
                    "event_id": evidence.event_id,
                },
            )
        )

    for hypothesis in hypotheses:
        for mapping in uow.thesis.list_mappings(hypothesis.hypothesis_id):
            if mapping.confirmation_status is not ConfirmationStatus.CONFIRMED:
                continue
            for observation in uow.observations.list_for_metric(
                thesis.security_id, mapping.metric_id
            ):
                if observation.observation_date > data_cutoff_at.date():
                    excluded["future_record"] += 1
                    continue
                if observation.ingested_at and observation.ingested_at > data_cutoff_at:
                    excluded["future_record"] += 1
                    continue
                if observation.source_document_id:
                    source_document = uow.documents.get(observation.source_document_id)
                    if (
                        source_document is None
                        or source_document.deleted_at is not None
                        or not permission.can_read_document(
                            actor, visibility_label=source_document.visibility_label
                        )
                    ):
                        excluded["missing_or_invisible_document"] += 1
                        continue
                value = (
                    str(observation.actual_value)
                    if observation.actual_value is not None
                    else "未提供"
                )
                sources.append(
                    _source(
                        retrospective_id,
                        source_type="metric_observation",
                        object_id=(
                            f"{thesis.security_id}:{mapping.metric_id}:{observation.period}"
                        ),
                        object_version=(
                            observation.data_version
                            or f"{observation.metric_version}:{observation.period_type}"
                        ),
                        content_hash=observation.data_version,
                        summary=f"{mapping.metric_id} {observation.period} 实际值 {value} {observation.unit}",
                        hypothesis_id=hypothesis.hypothesis_id,
                        disclosed_at=_date_as_datetime(
                            observation.observation_date, data_cutoff_at
                        ),
                        metadata={
                            "metric_id": mapping.metric_id,
                            "period": observation.period,
                            "period_type": observation.period_type,
                            "actual_value": value,
                            "expected_value": (
                                str(observation.expected_value)
                                if observation.expected_value is not None
                                else None
                            ),
                            "unit": observation.unit,
                            "source_document_id": observation.source_document_id,
                            "data_version": observation.data_version,
                        },
                    )
                )

    acted_suggestions = []
    for suggestion in uow.suggestions.list_for_thesis(thesis_id):
        if suggestion.acted_at is None:
            continue
        if suggestion.acted_at > data_cutoff_at:
            excluded["future_record"] += 1
            continue
        acted_suggestions.append(suggestion)
        sources.append(
            _source(
                retrospective_id,
                source_type="status_decision",
                object_id=str(suggestion.suggestion_id or _short_hash(asdict(suggestion))),
                object_version=suggestion.rule_version,
                summary=(
                    f"状态建议 {suggestion.current_status.value} → "
                    f"{suggestion.suggested_status.value}，人工处置：{suggestion.human_action or '未填写'}"
                ),
                confirmed_at=suggestion.acted_at,
                metadata={
                    "human_action": suggestion.human_action,
                    "human_reason": suggestion.human_reason,
                    "acted_by": suggestion.acted_by,
                    "reasons": list(suggestion.reasons),
                    "triggered_hypotheses": list(suggestion.triggered_hypotheses),
                },
            )
        )

    resolved_tasks = []
    for task in uow.reviews.list_for_thesis(thesis_id, limit=100):
        if task.state != "已完成" or task.resolved_at is None:
            continue
        if task.resolved_at > data_cutoff_at:
            excluded["future_record"] += 1
            continue
        resolved_tasks.append(task)
        sources.append(
            _source(
                retrospective_id,
                source_type="review_task",
                object_id=task.task_id,
                summary=f"{task.trigger}复核：{task.resolution or '已完成'}"[:1000],
                confirmed_at=task.resolved_at,
                metadata={
                    "trigger": task.trigger,
                    "priority": task.priority,
                    "assignee": task.assignee,
                },
            )
        )

    for audit_item in uow.audit.list_for_object("thesis", thesis_id):
        if audit_item.occurred_at is None or audit_item.occurred_at > data_cutoff_at:
            continue
        if audit_item.occurred_at.date() < period_start:
            continue
        sources.append(
            _source(
                retrospective_id,
                source_type="audit",
                object_id=f"{thesis_id}:{_short_hash([audit_item.action, audit_item.actor, _iso(audit_item.occurred_at)])}",
                summary=f"{audit_item.action} · {audit_item.actor}",
                confirmed_at=audit_item.occurred_at,
                metadata={"action": audit_item.action, "actor": audit_item.actor},
            )
        )

    sources = _deduplicate(sources)
    if len(sources) > settings.retrospective_max_sources:
        raise ValidationFailed(
            f"来源数量 {len(sources)} 超过上限 {settings.retrospective_max_sources}，请缩小复盘区间"
        )

    checks: list[tuple[str, bool]] = [
        ("缺少复盘期初正式逻辑版本", baseline is not None),
        ("缺少截止时点前正式逻辑版本", endpoint is not None),
        ("投资逻辑没有结构化假设", bool(hypotheses)),
    ]
    if confirmed_evidence_count:
        checks.append(
            (
                "部分已确认证据缺少可打开正文、有效 locator 或当时可见 Revision",
                traced_evidence_count == confirmed_evidence_count,
            )
        )
    if acted_suggestions:
        checks.append(
            (
                "部分状态处置缺少原因、操作者或时间",
                all(
                    item.human_reason and item.acted_by and item.acted_at
                    for item in acted_suggestions
                ),
            )
        )
    if resolved_tasks:
        checks.append(
            (
                "部分已完成复核任务缺少处置结论",
                all(item.resolution for item in resolved_tasks),
            )
        )
    completed = sum(passed for _, passed in checks)
    applicable = len(checks)
    missing.extend(message for message, passed in checks if not passed)
    score = Decimal(completed) / Decimal(applicable) if applicable else Decimal("0")
    fingerprint = fingerprint_sources(sources, data_cutoff_at=data_cutoff_at)
    return SourcePreview(
        thesis=thesis,
        hypotheses=hypotheses,
        sources=tuple(sources),
        source_fingerprint=fingerprint,
        completeness_completed=completed,
        completeness_applicable=applicable,
        completeness_score=score.quantize(Decimal("0.000001")),
        missing_items=tuple(dict.fromkeys(missing)),
        excluded_counts=excluded,
    )


def bind_sources(
    sources: tuple[RetrospectiveSourceRecord, ...], retrospective_id: str
) -> list[RetrospectiveSourceRecord]:
    """Bind preview sources to the persisted report and re-key immutable rows."""
    return [
        replace(
            item,
            retrospective_id=retrospective_id,
            source_id=_source_id(
                retrospective_id,
                item.source_type,
                item.object_id,
                item.object_version,
                item.locator,
            ),
        )
        for item in sources
    ]


def fingerprint_sources(
    sources: list[RetrospectiveSourceRecord] | tuple[RetrospectiveSourceRecord, ...],
    *,
    data_cutoff_at: datetime,
) -> str:
    payload = [
        {
            "source_type": item.source_type,
            "object_id": item.object_id,
            "object_version": item.object_version,
            "locator": item.locator,
            "content_hash": item.content_hash,
            "disclosed_at": _iso(item.disclosed_at),
            "confirmed_at": _iso(item.confirmed_at),
        }
        for item in sorted(
            sources,
            key=lambda value: (
                value.source_type,
                value.object_id,
                value.object_version or "",
                value.locator or "",
            ),
        )
    ]
    raw = json.dumps(
        {"data_cutoff_at": data_cutoff_at.isoformat(), "sources": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(raw.encode("utf-8")).hexdigest()


def _source(
    retrospective_id: str,
    *,
    source_type: str,
    object_id: str,
    summary: str,
    object_version: str | None = None,
    locator: str | None = None,
    content_hash: str | None = None,
    direction: str | None = None,
    strength: str | None = None,
    hypothesis_id: str | None = None,
    disclosed_at: datetime | None = None,
    confirmed_at: datetime | None = None,
    visibility_label: str = "内部",
    metadata: dict[str, Any] | None = None,
) -> RetrospectiveSourceRecord:
    return RetrospectiveSourceRecord(
        source_id=_source_id(retrospective_id, source_type, object_id, object_version, locator),
        retrospective_id=retrospective_id,
        source_type=source_type,
        object_id=object_id,
        object_version=object_version,
        locator=locator,
        content_hash=content_hash,
        summary=summary.strip()[:2000] or object_id,
        direction=direction,
        strength=strength,
        hypothesis_id=hypothesis_id,
        disclosed_at=disclosed_at,
        confirmed_at=confirmed_at,
        visibility_label=visibility_label,
        metadata=metadata or {},
    )


def _source_id(
    retrospective_id: str,
    source_type: str,
    object_id: str,
    object_version: str | None,
    locator: str | None,
) -> str:
    return "RCS-" + _short_hash(
        [retrospective_id, source_type, object_id, object_version or "", locator or ""]
    )


def _short_hash(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return sha256(raw.encode("utf-8")).hexdigest()[:24]


def _deduplicate(
    sources: list[RetrospectiveSourceRecord],
) -> list[RetrospectiveSourceRecord]:
    unique: dict[tuple[str, str, str | None, str | None], RetrospectiveSourceRecord] = {}
    for item in sources:
        key = (item.source_type, item.object_id, item.object_version, item.locator)
        unique.setdefault(key, item)
    return sorted(
        unique.values(),
        key=lambda item: (
            item.disclosed_at or item.confirmed_at or datetime.min.replace(tzinfo=now().tzinfo),
            item.source_type,
            item.object_id,
        ),
    )


def _date_as_datetime(value: date, reference: datetime) -> datetime:
    return datetime.combine(value, datetime.min.time(), tzinfo=reference.tzinfo)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
