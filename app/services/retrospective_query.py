"""Read models for the retrospective center."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

from app.core.domain import (
    RetrospectiveQuery,
    RetrospectiveRecord,
    RetrospectiveSourceRecord,
    RetrospectiveVersionRecord,
    ThesisRecord,
    UnitOfWork,
)
from app.core.enums import RetrospectiveState
from app.services import permission
from app.services.errors import NotVisible, ValidationFailed
from app.services.permission import Actor


@dataclass(frozen=True)
class RetrospectiveDetail:
    record: RetrospectiveRecord
    thesis: ThesisRecord
    sources: tuple[RetrospectiveSourceRecord, ...]
    versions: tuple[RetrospectiveVersionRecord, ...]
    visible_content: dict[str, object]
    allowed_actions: tuple[str, ...]


def get_visible(
    uow: UnitOfWork,
    *,
    retrospective_id: str,
    actor: Actor,
) -> tuple[RetrospectiveRecord, ThesisRecord]:
    record = uow.retrospectives.get(retrospective_id)
    if record is None:
        raise NotVisible("复盘不存在或无访问权限")
    thesis = uow.thesis.get(record.thesis_id)
    if thesis is None:
        raise NotVisible("复盘不存在或无访问权限")
    if actor.user_id in {record.owner, record.reviewer}:
        return record, thesis
    if record.current_version <= 0 or record.state not in {
        RetrospectiveState.PUBLISHED.value,
        RetrospectiveState.ARCHIVED.value,
    }:
        raise NotVisible("复盘不存在或无访问权限")
    permission.ensure_thesis_visible(
        actor,
        thesis_id=thesis.thesis_id,
        owner=thesis.owner,
        visibility=record.visibility,
        team=record.team,
    )
    return record, thesis


def detail(
    uow: UnitOfWork,
    *,
    retrospective_id: str,
    actor: Actor,
) -> RetrospectiveDetail:
    record, thesis = get_visible(uow, retrospective_id=retrospective_id, actor=actor)
    sources = tuple(
        _source_for_actor(uow, item, actor)
        for item in uow.retrospectives.list_sources(retrospective_id)
    )
    versions = tuple(uow.retrospectives.list_versions(retrospective_id))
    can_see_draft = actor.user_id in {record.owner, record.reviewer}
    has_revision_draft = bool(str(record.draft_content.get("revision_reason") or "").strip())
    if can_see_draft and (
        record.state
        in {
            RetrospectiveState.DRAFT.value,
            RetrospectiveState.IN_REVIEW.value,
        }
        or (record.state == RetrospectiveState.PUBLISHED.value and has_revision_draft)
    ):
        visible_content = record.draft_content
    elif versions:
        visible_content = versions[0].content
    else:
        visible_content = record.draft_content if can_see_draft else {}
    return RetrospectiveDetail(
        record=record,
        thesis=thesis,
        sources=sources,
        versions=versions,
        visible_content=dict(visible_content),
        allowed_actions=_allowed_actions(record, actor),
    )


def search(
    uow: UnitOfWork,
    *,
    actor: Actor,
    query: RetrospectiveQuery,
) -> tuple[list[RetrospectiveRecord], int]:
    if query.limit < 1 or query.limit > 100:
        raise ValidationFailed("复盘列表每页数量必须在 1 到 100 之间")
    if query.offset < 0:
        raise ValidationFailed("复盘列表 offset 不能为负数")
    if query.direction not in {"asc", "desc"}:
        raise ValidationFailed("复盘列表排序方向无效")
    if query.sort not in {
        "updated_at",
        "published_at",
        "period_end",
        "completeness_score",
    }:
        raise ValidationFailed("复盘列表排序字段无效")
    if query.hypothesis_result not in {
        None,
        "成立",
        "部分成立",
        "不成立",
        "证据不足",
        "尚未到期",
    }:
        raise ValidationFailed("假设结果筛选值无效")
    if query.completeness_min is not None and not 0 <= query.completeness_min <= 1:
        raise ValidationFailed("完整度下限必须在 0 到 1 之间")
    if query.completeness_max is not None and not 0 <= query.completeness_max <= 1:
        raise ValidationFailed("完整度上限必须在 0 到 1 之间")
    if (
        query.completeness_min is not None
        and query.completeness_max is not None
        and query.completeness_min > query.completeness_max
    ):
        raise ValidationFailed("完整度下限不能高于上限")
    return uow.retrospectives.search_visible(
        actor_id=actor.user_id,
        teams=tuple(sorted(actor.teams)),
        query=query,
    )


def overview(uow: UnitOfWork, *, actor: Actor) -> dict[str, object]:
    rows, total = search(
        uow,
        actor=actor,
        query=RetrospectiveQuery(limit=100, offset=0),
    )
    while len(rows) < total:
        page, _ = search(
            uow,
            actor=actor,
            query=RetrospectiveQuery(limit=100, offset=len(rows)),
        )
        if not page:
            break
        rows.extend(page)
    state_counts = Counter(row.state for row in rows)
    version_keys: set[tuple[str, str | None]] = set()
    validated = 0
    pending = 0
    strong_total = 0
    strong_handled = 0
    scores: list[Decimal] = []
    for row in rows:
        scores.append(row.completeness_score)
        sources = uow.retrospectives.list_sources(row.retrospective_id)
        strong = [
            item
            for item in sources
            if item.source_type == "confirmed_evidence"
            and item.direction == "冲突"
            and item.strength == "高"
        ]
        strong_total += len(strong)
        for item in sources:
            if item.source_type == "thesis_version":
                version_keys.add((item.object_id, item.object_version))
        versions = uow.retrospectives.list_versions(row.retrospective_id)
        content = versions[0].content if versions else row.draft_content
        assessments = content.get("hypothesis_assessments")
        if isinstance(assessments, list):
            for item in assessments:
                if not isinstance(item, dict):
                    continue
                result = str(item.get("result") or "")
                if result in {"成立", "部分成立", "不成立"} and versions:
                    validated += 1
                elif result in {"证据不足", "尚未到期"}:
                    pending += 1
        cited = _source_ids(content)
        conflict_resolution = str(content.get("conflict_resolution") or "").strip()
        strong_handled += sum(
            item.source_id in cited or bool(conflict_resolution) for item in strong
        )
    average = (
        (sum(scores, Decimal("0")) / Decimal(len(scores))).quantize(Decimal("0.000001"))
        if scores
        else Decimal("0")
    )
    return {
        "as_of": max((row.updated_at for row in rows if row.updated_at), default=None),
        "total": total,
        "state_counts": dict(state_counts),
        "logic_changes": len(version_keys),
        "validated_hypotheses": validated,
        "pending_hypotheses": pending,
        "strong_conflicts_handled": strong_handled,
        "strong_conflicts_total": strong_total,
        "average_completeness": average,
        "pending_reports": state_counts.get("草稿", 0) + state_counts.get("待评审", 0),
        "is_truncated": total > len(rows),
    }


def timeline(uow: UnitOfWork, *, retrospective_id: str, actor: Actor) -> list[dict[str, Any]]:
    record, _ = get_visible(uow, retrospective_id=retrospective_id, actor=actor)
    items = []
    for raw_source in uow.retrospectives.list_sources(retrospective_id):
        source = _source_for_actor(uow, raw_source, actor)
        items.append(
            {
                "source_id": source.source_id,
                "source_type": source.source_type,
                "title": _source_title(source),
                "summary": source.summary,
                "occurred_at": source.disclosed_at or source.confirmed_at,
                "disclosed_at": source.disclosed_at,
                "confirmed_at": source.confirmed_at,
                "direction": source.direction,
                "strength": source.strength,
                "hypothesis_id": source.hypothesis_id,
                "locator": source.locator,
                "object_id": source.object_id,
                "object_version": source.object_version,
                "metadata": source.metadata,
            }
        )
    items.sort(
        key=lambda item: (
            item["occurred_at"] is None,
            item["occurred_at"] or record.data_cutoff_at,
            item["source_id"],
        )
    )
    return items


def _allowed_actions(record: RetrospectiveRecord, actor: Actor) -> tuple[str, ...]:
    actions = ["view"]
    if actor.user_id == record.owner and record.state != RetrospectiveState.ARCHIVED.value:
        has_revision_draft = bool(str(record.draft_content.get("revision_reason") or "").strip())
        actions.append("export")
        if record.state == RetrospectiveState.DRAFT.value:
            actions.extend(["edit", "ai_draft", "submit", "publish"])
        elif record.state == RetrospectiveState.IN_REVIEW.value:
            actions.append("publish")
        elif record.state == RetrospectiveState.PUBLISHED.value:
            if has_revision_draft:
                actions.extend(["edit", "ai_draft", "publish"])
            else:
                actions.extend(["revise", "archive"])
    if actor.user_id == record.reviewer and record.state == RetrospectiveState.IN_REVIEW.value:
        actions.append("return")
    if record.current_version > 0:
        actions.append("export")
    return tuple(dict.fromkeys(actions))


def _source_ids(content: dict[str, object]) -> set[str]:
    result: set[str] = set()
    citations = content.get("citations")
    if isinstance(citations, list):
        result.update(str(item) for item in citations)
    assessments = content.get("hypothesis_assessments")
    if isinstance(assessments, list):
        for item in assessments:
            if isinstance(item, dict) and isinstance(item.get("source_ids"), list):
                result.update(str(value) for value in item["source_ids"])
    return result


def _source_title(source: RetrospectiveSourceRecord) -> str:
    return {
        "thesis_version": "投资逻辑版本",
        "confirmed_evidence": "已确认证据",
        "metric_observation": "指标观测",
        "status_decision": "状态处置",
        "review_task": "复核任务",
        "audit": "研究动作",
    }.get(source.source_type, source.source_type)


def _source_for_actor(
    uow: UnitOfWork, source: RetrospectiveSourceRecord, actor: Actor
) -> RetrospectiveSourceRecord:
    if source.source_type != "confirmed_evidence":
        return source
    document_id = str(source.metadata.get("document_id") or "")
    document = uow.documents.get(document_id) if document_id else None
    unavailable = (
        document is None
        or document.deleted_at is not None
        or not permission.can_read_document(actor, visibility_label=document.visibility_label)
    )
    if not unavailable:
        return source
    return replace(
        source,
        locator=None,
        content_hash=None,
        summary="来源当前不可打开或无访问权限",
        metadata={"availability": "unavailable"},
    )
