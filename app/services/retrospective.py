"""Retrospective lifecycle and its human publication gate."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime
from uuid import uuid4

from app.core.config import Settings
from app.core.domain import (
    RetrospectiveRecord,
    RetrospectiveVersionRecord,
    UnitOfWork,
)
from app.core.enums import (
    HypothesisAssessment,
    RetrospectiveState,
    RetrospectiveType,
)
from app.core.timeutil import now
from app.services import audit, permission, retrospective_query, retrospective_sources
from app.services.errors import (
    ConcurrentUpdate,
    HumanGateRequired,
    NotVisible,
    ResourceConflict,
    ValidationFailed,
)
from app.services.permission import Actor


def preview_sources(
    uow: UnitOfWork,
    *,
    thesis_id: str,
    period_start: date,
    period_end: date,
    data_cutoff_at: datetime,
    actor: Actor,
    settings: Settings,
):
    return retrospective_sources.build_preview(
        uow,
        thesis_id=thesis_id,
        period_start=period_start,
        period_end=period_end,
        data_cutoff_at=data_cutoff_at,
        actor=actor,
        settings=settings,
    )


def create(
    uow: UnitOfWork,
    *,
    thesis_id: str,
    retrospective_type: str,
    title: str,
    period_start: date,
    period_end: date,
    data_cutoff_at: datetime,
    actor: Actor,
    settings: Settings,
    reviewer: str | None = None,
) -> RetrospectiveRecord:
    try:
        kind = RetrospectiveType(retrospective_type)
    except ValueError as exc:
        raise ValidationFailed("未知复盘类型") from exc
    if len(title.strip()) < 2:
        raise ValidationFailed("复盘标题不能为空")
    existing = uow.retrospectives.find_active(
        thesis_id=thesis_id,
        retrospective_type=kind.value,
        period_start=period_start,
        period_end=period_end,
    )
    if existing is not None:
        raise ResourceConflict(f"相同逻辑、类型和区间的复盘已存在：{existing.retrospective_id}")
    retrospective_id = f"RTP-{uuid4().hex}"
    preview = retrospective_sources.build_preview(
        uow,
        thesis_id=thesis_id,
        period_start=period_start,
        period_end=period_end,
        data_cutoff_at=data_cutoff_at,
        actor=actor,
        settings=settings,
        retrospective_id=retrospective_id,
    )
    if preview.thesis.owner != actor.user_id:
        raise HumanGateRequired("只有逻辑负责人可以创建正式复盘草稿")
    sources = retrospective_sources.bind_sources(preview.sources, retrospective_id)
    fingerprint = retrospective_sources.fingerprint_sources(sources, data_cutoff_at=data_cutoff_at)
    source_visibilities = {item.visibility_label for item in sources}
    source_requires_private = bool(source_visibilities & {"内部受限", "机密"})
    record = RetrospectiveRecord(
        retrospective_id=retrospective_id,
        thesis_id=thesis_id,
        retrospective_type=kind.value,
        title=title.strip(),
        period_start=period_start,
        period_end=period_end,
        data_cutoff_at=data_cutoff_at,
        owner=actor.user_id,
        reviewer=reviewer.strip() if reviewer and reviewer.strip() else None,
        visibility="私有" if source_requires_private else preview.thesis.visibility,
        team=None if source_requires_private else preview.thesis.team,
        source_fingerprint=fingerprint,
        source_count=len(sources),
        completeness_completed=preview.completeness_completed,
        completeness_applicable=preview.completeness_applicable,
        completeness_score=preview.completeness_score,
        draft_content=_initial_content(preview),
    )
    try:
        saved = uow.retrospectives.add(record)
    except RuntimeError as exc:
        if str(exc) == "retrospective_scope_conflict":
            raise ResourceConflict("相同逻辑、类型和区间的复盘已存在") from exc
        raise
    uow.retrospectives.add_sources(sources)
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action=audit.CREATE,
        object_type="retrospective",
        object_id=retrospective_id,
        detail={
            "thesis_id": thesis_id,
            "type": kind.value,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "data_cutoff_at": data_cutoff_at.isoformat(),
            "source_count": len(sources),
            "source_fingerprint": fingerprint,
        },
    )
    return saved


def save_draft(
    uow: UnitOfWork,
    *,
    retrospective_id: str,
    content: dict[str, object],
    expected_lock_version: int,
    actor: Actor,
    title: str | None = None,
) -> RetrospectiveRecord:
    record, _ = retrospective_query.get_visible(uow, retrospective_id=retrospective_id, actor=actor)
    if record.owner != actor.user_id:
        raise HumanGateRequired("只有复盘负责人可以编辑草稿")
    if record.state == RetrospectiveState.ARCHIVED.value:
        raise ValidationFailed("已归档复盘不能编辑")
    if record.state == RetrospectiveState.IN_REVIEW.value:
        raise ValidationFailed("待评审复盘需先退回才能编辑")
    if (
        record.state == RetrospectiveState.PUBLISHED.value
        and not str(record.draft_content.get("revision_reason") or "").strip()
    ):
        raise ValidationFailed("已发布复盘需先创建修订草稿")
    if record.current_version > 0 and title and title.strip() != record.title:
        raise ValidationFailed("首版修订不支持修改已发布复盘标题")
    _validate_content_shape(content)
    updated = replace(
        record,
        title=title.strip() if title and title.strip() else record.title,
        draft_content=_clean_content(content),
        lock_version=record.lock_version + 1,
        updated_at=now(),
    )
    _update(uow, updated, expected_lock_version=expected_lock_version)
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action=audit.EDIT,
        object_type="retrospective",
        object_id=retrospective_id,
        detail={"lock_version": updated.lock_version},
    )
    return updated


def submit(
    uow: UnitOfWork,
    *,
    retrospective_id: str,
    reviewer: str,
    expected_lock_version: int,
    actor: Actor,
) -> RetrospectiveRecord:
    record, _ = retrospective_query.get_visible(uow, retrospective_id=retrospective_id, actor=actor)
    if record.owner != actor.user_id:
        raise HumanGateRequired("只有复盘负责人可以提交评审")
    if record.state != RetrospectiveState.DRAFT.value:
        raise ValidationFailed("只有草稿可以提交评审")
    if not reviewer.strip():
        raise ValidationFailed("提交评审必须指定评审人")
    updated = replace(
        record,
        reviewer=reviewer.strip(),
        state=RetrospectiveState.IN_REVIEW.value,
        submitted_at=now(),
        lock_version=record.lock_version + 1,
        updated_at=now(),
    )
    _update(uow, updated, expected_lock_version=expected_lock_version)
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action="提交评审",
        object_type="retrospective",
        object_id=retrospective_id,
        detail={"reviewer": reviewer.strip()},
    )
    return updated


def return_for_revision(
    uow: UnitOfWork,
    *,
    retrospective_id: str,
    reason: str,
    expected_lock_version: int,
    actor: Actor,
) -> RetrospectiveRecord:
    record, _ = retrospective_query.get_visible(uow, retrospective_id=retrospective_id, actor=actor)
    if record.reviewer != actor.user_id:
        raise HumanGateRequired("只有指定评审人可以退回复盘")
    if record.state != RetrospectiveState.IN_REVIEW.value:
        raise ValidationFailed("只有待评审复盘可以退回")
    if len(reason.strip()) < 2:
        raise ValidationFailed("退回原因不能为空")
    content = dict(record.draft_content)
    content["review_feedback"] = reason.strip()
    updated = replace(
        record,
        state=RetrospectiveState.DRAFT.value,
        draft_content=content,
        lock_version=record.lock_version + 1,
        updated_at=now(),
    )
    _update(uow, updated, expected_lock_version=expected_lock_version)
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action="退回复盘",
        object_type="retrospective",
        object_id=retrospective_id,
        detail={"reason": reason.strip()},
    )
    return updated


def publish(
    uow: UnitOfWork,
    *,
    retrospective_id: str,
    publish_reason: str,
    expected_lock_version: int,
    actor: Actor,
) -> RetrospectiveRecord:
    record, thesis = retrospective_query.get_visible(
        uow, retrospective_id=retrospective_id, actor=actor
    )
    if record.owner != actor.user_id or thesis.owner != actor.user_id:
        raise HumanGateRequired("只有逻辑负责人可以发布复盘")
    if record.state not in {
        RetrospectiveState.DRAFT.value,
        RetrospectiveState.IN_REVIEW.value,
        RetrospectiveState.PUBLISHED.value,
    }:
        raise ValidationFailed("当前复盘状态不能发布")
    if len(publish_reason.strip()) < 2:
        raise ValidationFailed("发布说明不能为空")
    if (
        record.current_version > 0
        and not str(record.draft_content.get("revision_reason") or "").strip()
    ):
        raise ValidationFailed("已发布复盘需先创建修订草稿")
    sources = uow.retrospectives.list_sources(retrospective_id)
    _validate_for_publish(uow, record, record.draft_content, sources, actor)
    next_version = record.current_version + 1
    published_content = _clean_content(record.draft_content)
    version = RetrospectiveVersionRecord(
        retrospective_id=retrospective_id,
        version=next_version,
        content=published_content,
        source_fingerprint=record.source_fingerprint,
        published_by=actor.user_id,
        publish_reason=publish_reason.strip(),
        ai_run_id=record.ai_run_id,
        model_version=record.ai_model_version,
        prompt_version=record.ai_prompt_version,
        schema_version=record.ai_schema_version,
    )
    editable_content = dict(published_content)
    editable_content.pop("revision_reason", None)
    updated = replace(
        record,
        state=RetrospectiveState.PUBLISHED.value,
        draft_content=editable_content,
        current_version=next_version,
        published_at=now(),
        lock_version=record.lock_version + 1,
        updated_at=now(),
    )
    _update(uow, updated, expected_lock_version=expected_lock_version)
    uow.retrospectives.add_version(version)
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action=audit.PUBLISH,
        object_type="retrospective",
        object_id=retrospective_id,
        detail={
            "version": next_version,
            "publish_reason": publish_reason.strip(),
            "source_fingerprint": record.source_fingerprint,
        },
    )
    return updated


def start_revision(
    uow: UnitOfWork,
    *,
    retrospective_id: str,
    reason: str,
    expected_lock_version: int,
    actor: Actor,
) -> RetrospectiveRecord:
    record, _ = retrospective_query.get_visible(uow, retrospective_id=retrospective_id, actor=actor)
    if record.owner != actor.user_id:
        raise HumanGateRequired("只有复盘负责人可以创建修订")
    if record.state != RetrospectiveState.PUBLISHED.value or record.current_version <= 0:
        raise ValidationFailed("只有已发布复盘可以创建修订")
    if str(record.draft_content.get("revision_reason") or "").strip():
        raise ResourceConflict("当前已有未发布的修订草稿")
    if len(reason.strip()) < 2:
        raise ValidationFailed("修订原因不能为空")
    latest = uow.retrospectives.get_version(retrospective_id, record.current_version)
    if latest is None:
        raise ResourceConflict("最新发布版本不存在，不能创建修订")
    content = dict(latest.content)
    content["revision_reason"] = reason.strip()
    updated = replace(
        record,
        draft_content=content,
        lock_version=record.lock_version + 1,
        updated_at=now(),
    )
    _update(uow, updated, expected_lock_version=expected_lock_version)
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action="创建复盘修订",
        object_type="retrospective",
        object_id=retrospective_id,
        detail={"base_version": record.current_version, "reason": reason.strip()},
    )
    return updated


def archive(
    uow: UnitOfWork,
    *,
    retrospective_id: str,
    reason: str,
    expected_lock_version: int,
    actor: Actor,
) -> RetrospectiveRecord:
    record, _ = retrospective_query.get_visible(uow, retrospective_id=retrospective_id, actor=actor)
    if record.owner != actor.user_id:
        raise HumanGateRequired("只有复盘负责人可以归档")
    if record.state != RetrospectiveState.PUBLISHED.value:
        raise ValidationFailed("只有已发布复盘可以归档")
    if str(record.draft_content.get("revision_reason") or "").strip():
        raise ValidationFailed("存在未发布修订草稿，不能归档")
    if len(reason.strip()) < 2:
        raise ValidationFailed("归档原因不能为空")
    updated = replace(
        record,
        state=RetrospectiveState.ARCHIVED.value,
        archived_at=now(),
        lock_version=record.lock_version + 1,
        updated_at=now(),
    )
    _update(uow, updated, expected_lock_version=expected_lock_version)
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action="归档",
        object_type="retrospective",
        object_id=retrospective_id,
        detail={"reason": reason.strip()},
    )
    return updated


def export_published(
    uow: UnitOfWork,
    *,
    retrospective_id: str,
    format: str,
    actor: Actor,
    settings: Settings,
) -> tuple[bytes, str, str]:
    detail = retrospective_query.detail(uow, retrospective_id=retrospective_id, actor=actor)
    record = detail.record
    if record.current_version <= 0:
        raise ValidationFailed("未发布复盘不能导出")
    version = uow.retrospectives.get_version(retrospective_id, record.current_version)
    if version is None:
        raise ResourceConflict("发布版本不存在")
    if format == "json":
        payload = {
            "retrospective_id": retrospective_id,
            "version": version.version,
            "title": record.title,
            "thesis_id": record.thesis_id,
            "period_start": record.period_start.isoformat(),
            "period_end": record.period_end.isoformat(),
            "data_cutoff_at": record.data_cutoff_at.isoformat(),
            "source_fingerprint": version.source_fingerprint,
            "published_by": version.published_by,
            "published_at": version.created_at.isoformat() if version.created_at else None,
            "content": version.content,
            "sources": [_public_source(item) for item in detail.sources],
        }
        body = json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        media_type, suffix = "application/json", "json"
    elif format == "markdown":
        body = _markdown(record, version, detail.sources).encode("utf-8")
        media_type, suffix = "text/markdown; charset=utf-8", "md"
    else:
        raise ValidationFailed("首版只支持 markdown 或 json 导出")
    if len(body) > settings.retrospective_max_export_bytes:
        raise ValidationFailed("导出内容超过大小上限")
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action=audit.EXPORT,
        object_type="retrospective",
        object_id=retrospective_id,
        detail={"version": version.version, "format": format, "bytes": len(body)},
    )
    return body, media_type, f"{retrospective_id}-v{version.version}.{suffix}"


def _initial_content(preview) -> dict[str, object]:
    return {
        "summary": "",
        "original_judgement": preview.thesis.core_view,
        "key_changes": [],
        "hypothesis_assessments": [
            {
                "hypothesis_id": item.hypothesis_id,
                "statement": item.statement,
                "result": HypothesisAssessment.INSUFFICIENT.value,
                "rationale": "",
                "source_ids": [],
            }
            for item in preview.hypotheses
        ],
        "errors_and_omissions": "",
        "conflict_resolution": "",
        "source_gaps_acknowledgement": (
            "" if preview.missing_items else "当前预检无必需来源缺口。"
        ),
        "limitations": "",
        "next_actions": "",
        "citations": [],
    }


def _validate_content_shape(content: dict[str, object]) -> None:
    if not isinstance(content, dict):
        raise ValidationFailed("复盘草稿必须是结构化对象")
    if len(json.dumps(content, ensure_ascii=False, default=str)) > 200_000:
        raise ValidationFailed("复盘草稿内容过长")
    assessments = content.get("hypothesis_assessments", [])
    if not isinstance(assessments, list):
        raise ValidationFailed("假设结论必须是数组")
    allowed = {item.value for item in HypothesisAssessment}
    for item in assessments:
        if not isinstance(item, dict):
            raise ValidationFailed("假设结论格式无效")
        if str(item.get("result") or "") not in allowed:
            raise ValidationFailed("假设结论枚举无效")
        if not isinstance(item.get("source_ids", []), list):
            raise ValidationFailed("假设结论来源必须是数组")


def _validate_for_publish(uow, record, content, sources, actor: Actor) -> None:
    _validate_content_shape(content)
    for field, label in (
        ("summary", "复盘摘要"),
        ("errors_and_omissions", "误差与遗漏"),
        ("limitations", "方法与数据局限"),
        ("next_actions", "后续研究建议"),
    ):
        if len(str(content.get(field) or "").strip()) < 2:
            raise ValidationFailed(f"发布前必须填写{label}")
    if (
        record.completeness_score < 1
        and len(str(content.get("source_gaps_acknowledgement") or "").strip()) < 2
    ):
        raise ValidationFailed("来源不完整时必须填写来源缺口说明")
    source_map = {item.source_id: item for item in sources}
    if not source_map:
        raise ValidationFailed("复盘没有冻结来源，不能发布")
    assessments = content.get("hypothesis_assessments")
    if not isinstance(assessments, list) or not assessments:
        raise ValidationFailed("发布前必须逐条评估假设")
    cited: set[str] = set()
    for item in assessments:
        assert isinstance(item, dict)
        result = str(item.get("result") or "")
        rationale = str(item.get("rationale") or "").strip()
        source_ids = {str(value) for value in item.get("source_ids", [])}
        if len(rationale) < 2:
            raise ValidationFailed("每条假设结论都必须填写判断理由")
        if (
            result
            in {
                HypothesisAssessment.SUPPORTED.value,
                HypothesisAssessment.PARTIAL.value,
                HypothesisAssessment.REFUTED.value,
            }
            and not source_ids
        ):
            raise ValidationFailed("成立、部分成立或不成立的假设必须选择至少一项依据")
        unknown = source_ids - source_map.keys()
        if unknown:
            raise ValidationFailed("假设结论引用了来源白名单外的记录")
        cited.update(source_ids)
    citations = content.get("citations", [])
    if not isinstance(citations, list):
        raise ValidationFailed("复盘引用必须是数组")
    citation_ids = {str(value) for value in citations}
    if citation_ids - source_map.keys():
        raise ValidationFailed("复盘引用了来源白名单外的记录")
    cited.update(citation_ids)
    strong_conflicts = [
        item
        for item in sources
        if item.source_type == "confirmed_evidence"
        and item.direction == "冲突"
        and item.strength == "高"
    ]
    if (
        strong_conflicts
        and not str(content.get("conflict_resolution") or "").strip()
        and any(item.source_id not in cited for item in strong_conflicts)
    ):
        raise ValidationFailed("高强度冲突必须被引用并解释，或填写统一冲突处理说明")
    for source in sources:
        if source.source_type != "confirmed_evidence" or source.source_id not in cited:
            continue
        if not source.locator:
            raise ValidationFailed("已确认证据缺少 locator，不能发布")
        document_id = str(source.metadata.get("document_id") or "")
        document = uow.documents.get(document_id) if document_id else None
        if document is None or document.deleted_at is not None:
            raise ValidationFailed("复盘引用的原文当前不可打开")
        if not permission.can_read_document(actor, visibility_label=document.visibility_label):
            raise NotVisible("复盘引用的原文不存在或无访问权限")


def _update(uow: UnitOfWork, record: RetrospectiveRecord, *, expected_lock_version: int) -> None:
    if expected_lock_version != record.lock_version - 1:
        raise ConcurrentUpdate("复盘已被其他操作更新，请刷新后重试")
    try:
        uow.retrospectives.update(record, expected_lock_version=expected_lock_version)
    except RuntimeError as exc:
        if str(exc) == "retrospective_lock_conflict":
            raise ConcurrentUpdate("复盘已被其他操作更新，请刷新后重试") from exc
        raise


def _clean_content(content: dict[str, object]) -> dict[str, object]:
    return json.loads(json.dumps(content, ensure_ascii=False, default=str))


def _public_source(item) -> dict[str, object]:
    return {
        "source_id": item.source_id,
        "source_type": item.source_type,
        "object_id": item.object_id,
        "object_version": item.object_version,
        "locator": item.locator,
        "summary": item.summary,
        "direction": item.direction,
        "strength": item.strength,
        "hypothesis_id": item.hypothesis_id,
        "disclosed_at": item.disclosed_at.isoformat() if item.disclosed_at else None,
        "confirmed_at": item.confirmed_at.isoformat() if item.confirmed_at else None,
    }


def _markdown(record, version, sources) -> str:
    content = version.content
    lines = [
        f"# {record.title}",
        "",
        f"- 复盘编号：`{record.retrospective_id}`",
        f"- 发布版本：v{version.version}",
        f"- 复盘区间：{record.period_start.isoformat()} 至 {record.period_end.isoformat()}",
        f"- 数据截止：{record.data_cutoff_at.isoformat()}",
        f"- 来源指纹：`{version.source_fingerprint}`",
        f"- 发布人：{version.published_by}",
        "",
        "## 摘要",
        "",
        str(content.get("summary") or ""),
        "",
        "## 原判断与关键变化",
        "",
        str(content.get("original_judgement") or ""),
    ]
    changes = content.get("key_changes")
    if isinstance(changes, list):
        lines.extend([f"- {item}" for item in changes])
    lines.extend(["", "## 假设验证", ""])
    assessments = content.get("hypothesis_assessments")
    if isinstance(assessments, list):
        for item in assessments:
            if not isinstance(item, dict):
                continue
            lines.extend(
                [
                    f"### {item.get('hypothesis_id')} · {item.get('result')}",
                    "",
                    str(item.get("statement") or ""),
                    "",
                    str(item.get("rationale") or ""),
                    "",
                    "依据：" + "、".join(str(x) for x in item.get("source_ids", [])),
                    "",
                ]
            )
    for key, title in (
        ("errors_and_omissions", "误差与遗漏"),
        ("conflict_resolution", "强反证处理"),
        ("limitations", "局限"),
        ("next_actions", "后续研究建议"),
    ):
        lines.extend([f"## {title}", "", str(content.get(key) or ""), ""])
    lines.extend(["## 来源", ""])
    for source in sources:
        locator = f" · `{source.locator}`" if source.locator else ""
        lines.append(f"- [{source.source_id}] {source.summary}{locator}")
    return "\n".join(lines).strip() + "\n"
