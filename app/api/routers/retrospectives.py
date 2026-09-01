"""Permission-aware retrospective center endpoints."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, NoReturn

from fastapi import APIRouter, HTTPException, Query, Response

from app.ai.errors import ModelUnavailable
from app.api.deps import ActorDep, SettingsDep, UowDep
from app.core.domain import (
    RetrospectiveQuery,
    RetrospectiveRecord,
    RetrospectiveSourceRecord,
    RetrospectiveVersionRecord,
    ThesisRecord,
)
from app.schemas.retrospective import (
    AiDraftIn,
    AiDraftOut,
    PreviewHypothesisOut,
    PublishIn,
    ReasonActionIn,
    RetrospectiveCreateIn,
    RetrospectiveDetailOut,
    RetrospectiveDraftIn,
    RetrospectiveOut,
    RetrospectiveOverviewOut,
    RetrospectivePageOut,
    RetrospectiveSourceOut,
    RetrospectiveVersionOut,
    SourcePreviewIn,
    SourcePreviewOut,
    SubmitIn,
    TimelineItemOut,
)
from app.services import retrospective as retrospective_service
from app.services import retrospective_query
from app.services.errors import (
    ConcurrentUpdate,
    HumanGateRequired,
    NotVisible,
    ResourceConflict,
    ValidationFailed,
)

router = APIRouter(prefix="/retrospectives", tags=["retrospectives"])


def _enabled(conf) -> None:
    if not conf.retrospective_center_enabled:
        raise HTTPException(status_code=404, detail="复盘中心未启用")


def _raise(exc: Exception) -> NoReturn:
    if isinstance(exc, NotVisible):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, HumanGateRequired):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, ConcurrentUpdate | ResourceConflict):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ModelUnavailable):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if isinstance(exc, ValidationFailed):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


def _source_out(item: RetrospectiveSourceRecord) -> RetrospectiveSourceOut:
    return RetrospectiveSourceOut(**item.__dict__)


def _version_out(item: RetrospectiveVersionRecord) -> RetrospectiveVersionOut:
    return RetrospectiveVersionOut(**item.__dict__)


def _record_out(record: RetrospectiveRecord, thesis: ThesisRecord, uow) -> RetrospectiveOut:
    versions = uow.retrospectives.list_versions(record.retrospective_id)
    content = versions[0].content if versions else record.draft_content
    assessments = content.get("hypothesis_assessments")
    result_counts: dict[str, int] = {}
    cited: set[str] = set()
    raw_citations = content.get("citations")
    if isinstance(raw_citations, list):
        cited.update(str(value) for value in raw_citations)
    if isinstance(assessments, list):
        for item in assessments:
            if not isinstance(item, dict):
                continue
            result = str(item.get("result") or "证据不足")
            result_counts[result] = result_counts.get(result, 0) + 1
            if isinstance(item.get("source_ids"), list):
                cited.update(str(value) for value in item["source_ids"])
    strong = [
        item
        for item in uow.retrospectives.list_sources(record.retrospective_id)
        if item.source_type == "confirmed_evidence"
        and item.direction == "冲突"
        and item.strength == "高"
    ]
    conflict_resolution = str(content.get("conflict_resolution") or "").strip()
    handled = sum(item.source_id in cited or bool(conflict_resolution) for item in strong)
    candidate_status = str(record.ai_candidate.get("status") or "") if record.ai_candidate else ""
    return RetrospectiveOut(
        **record.__dict__,
        thesis_title=thesis.title,
        security_id=thesis.security_id,
        ai_status=(
            "生成失败"
            if candidate_status == "failed"
            else "候选可用"
            if record.ai_candidate
            else "未生成"
        ),
        hypothesis_result_counts=result_counts,
        strong_conflicts_handled=handled,
        strong_conflicts_total=len(strong),
    )


def _get_thesis(uow, record: RetrospectiveRecord) -> ThesisRecord:
    thesis = uow.thesis.get(record.thesis_id)
    if thesis is None:
        raise NotVisible("复盘不存在或无访问权限")
    return thesis


@router.get("/overview", response_model=RetrospectiveOverviewOut)
def overview(actor: ActorDep, conf: SettingsDep, uow: UowDep) -> RetrospectiveOverviewOut:
    _enabled(conf)
    values = retrospective_query.overview(uow, actor=actor)
    values["definitions"] = {
        "logic_changes": "当前可见复盘来源中的正式逻辑版本数",
        "validated_hypotheses": "已发布版本中成立、部分成立或不成立的假设数",
        "strong_conflicts_handled": "被引用或填写统一说明的高强度冲突数/总数",
        "average_completeness": "可用必需记录项/适用必需记录项的可见复盘平均值",
    }
    return RetrospectiveOverviewOut(**values)


@router.get("", response_model=RetrospectivePageOut)
def list_retrospectives(
    actor: ActorDep,
    conf: SettingsDep,
    uow: UowDep,
    q: str | None = None,
    state: str | None = None,
    retrospective_type: str | None = None,
    owner: str | None = None,
    reviewer: str | None = None,
    security_id: str | None = None,
    industry: str | None = None,
    hypothesis_result: str | None = None,
    has_strong_conflict: bool | None = None,
    completeness_min: Annotated[Decimal | None, Query(ge=0, le=1)] = None,
    completeness_max: Annotated[Decimal | None, Query(ge=0, le=1)] = None,
    period_start: date | None = None,
    period_end: date | None = None,
    published_start: date | None = None,
    published_end: date | None = None,
    sort: str = "updated_at",
    direction: str = "desc",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RetrospectivePageOut:
    _enabled(conf)
    try:
        records, total = retrospective_query.search(
            uow,
            actor=actor,
            query=RetrospectiveQuery(
                query=q,
                state=state,
                retrospective_type=retrospective_type,
                owner=owner,
                reviewer=reviewer,
                security_id=security_id,
                industry=industry,
                hypothesis_result=hypothesis_result,
                has_strong_conflict=has_strong_conflict,
                completeness_min=completeness_min,
                completeness_max=completeness_max,
                period_start=period_start,
                period_end=period_end,
                published_start=published_start,
                published_end=published_end,
                sort=sort,
                direction=direction,
                limit=limit,
                offset=offset,
            ),
        )
        items = [_record_out(item, _get_thesis(uow, item), uow) for item in records]
    except Exception as exc:
        _raise(exc)
    return RetrospectivePageOut(items=items, total=total, limit=limit, offset=offset)


@router.post("/source-preview", response_model=SourcePreviewOut)
def source_preview(
    payload: SourcePreviewIn,
    actor: ActorDep,
    conf: SettingsDep,
    uow: UowDep,
) -> SourcePreviewOut:
    _enabled(conf)
    try:
        preview = retrospective_service.preview_sources(
            uow,
            thesis_id=payload.thesis_id,
            period_start=payload.period_start,
            period_end=payload.period_end,
            data_cutoff_at=payload.data_cutoff_at,
            actor=actor,
            settings=conf,
        )
    except Exception as exc:
        _raise(exc)
    return _preview_out(preview)


def _preview_out(preview) -> SourcePreviewOut:
    return SourcePreviewOut(
        thesis_id=preview.thesis.thesis_id,
        thesis_title=preview.thesis.title,
        security_id=preview.thesis.security_id,
        owner=preview.thesis.owner,
        source_fingerprint=preview.source_fingerprint,
        source_count=len(preview.sources),
        completeness_completed=preview.completeness_completed,
        completeness_applicable=preview.completeness_applicable,
        completeness_score=preview.completeness_score,
        missing_items=list(preview.missing_items),
        excluded_counts=preview.excluded_counts,
        hypotheses=[
            PreviewHypothesisOut(
                hypothesis_id=item.hypothesis_id,
                name=item.name,
                statement=item.statement,
                status=item.status,
            )
            for item in preview.hypotheses
        ],
        sources=[_source_out(item) for item in preview.sources],
    )


@router.post("", response_model=RetrospectiveOut, status_code=201)
def create_retrospective(
    payload: RetrospectiveCreateIn,
    actor: ActorDep,
    conf: SettingsDep,
    uow: UowDep,
) -> RetrospectiveOut:
    _enabled(conf)
    try:
        record = retrospective_service.create(
            uow,
            thesis_id=payload.thesis_id,
            retrospective_type=payload.retrospective_type,
            title=payload.title,
            period_start=payload.period_start,
            period_end=payload.period_end,
            data_cutoff_at=payload.data_cutoff_at,
            reviewer=payload.reviewer,
            actor=actor,
            settings=conf,
        )
        thesis = _get_thesis(uow, record)
    except Exception as exc:
        _raise(exc)
    return _record_out(record, thesis, uow)


@router.get("/{retrospective_id}", response_model=RetrospectiveDetailOut)
def get_retrospective(
    retrospective_id: str, actor: ActorDep, conf: SettingsDep, uow: UowDep
) -> RetrospectiveDetailOut:
    _enabled(conf)
    try:
        detail = retrospective_query.detail(uow, retrospective_id=retrospective_id, actor=actor)
    except Exception as exc:
        _raise(exc)
    return RetrospectiveDetailOut(
        retrospective=_record_out(detail.record, detail.thesis, uow),
        content=detail.visible_content,
        ai_candidate=detail.record.ai_candidate,
        sources=[_source_out(item) for item in detail.sources],
        versions=[_version_out(item) for item in detail.versions],
        allowed_actions=list(detail.allowed_actions),
    )


@router.get("/{retrospective_id}/timeline", response_model=list[TimelineItemOut])
def get_timeline(
    retrospective_id: str, actor: ActorDep, conf: SettingsDep, uow: UowDep
) -> list[TimelineItemOut]:
    _enabled(conf)
    try:
        return [
            TimelineItemOut(**item)
            for item in retrospective_query.timeline(
                uow, retrospective_id=retrospective_id, actor=actor
            )
        ]
    except Exception as exc:
        _raise(exc)


@router.get("/{retrospective_id}/sources", response_model=list[RetrospectiveSourceOut])
def get_sources(
    retrospective_id: str, actor: ActorDep, conf: SettingsDep, uow: UowDep
) -> list[RetrospectiveSourceOut]:
    _enabled(conf)
    try:
        detail = retrospective_query.detail(uow, retrospective_id=retrospective_id, actor=actor)
        return [_source_out(item) for item in detail.sources]
    except Exception as exc:
        _raise(exc)


@router.get("/{retrospective_id}/versions", response_model=list[RetrospectiveVersionOut])
def get_versions(
    retrospective_id: str, actor: ActorDep, conf: SettingsDep, uow: UowDep
) -> list[RetrospectiveVersionOut]:
    _enabled(conf)
    try:
        retrospective_query.get_visible(uow, retrospective_id=retrospective_id, actor=actor)
        return [_version_out(item) for item in uow.retrospectives.list_versions(retrospective_id)]
    except Exception as exc:
        _raise(exc)


@router.get("/{retrospective_id}/versions/{version}", response_model=RetrospectiveVersionOut)
def get_version(
    retrospective_id: str,
    version: int,
    actor: ActorDep,
    conf: SettingsDep,
    uow: UowDep,
) -> RetrospectiveVersionOut:
    _enabled(conf)
    try:
        retrospective_query.get_visible(uow, retrospective_id=retrospective_id, actor=actor)
        item = uow.retrospectives.get_version(retrospective_id, version)
        if item is None:
            raise NotVisible("复盘版本不存在或无访问权限")
        return _version_out(item)
    except Exception as exc:
        _raise(exc)


@router.patch("/{retrospective_id}/draft", response_model=RetrospectiveOut)
def save_draft(
    retrospective_id: str,
    payload: RetrospectiveDraftIn,
    actor: ActorDep,
    conf: SettingsDep,
    uow: UowDep,
) -> RetrospectiveOut:
    _enabled(conf)
    try:
        record = retrospective_service.save_draft(
            uow,
            retrospective_id=retrospective_id,
            content=payload.content,
            expected_lock_version=payload.lock_version,
            actor=actor,
            title=payload.title,
        )
        thesis = _get_thesis(uow, record)
    except Exception as exc:
        _raise(exc)
    return _record_out(record, thesis, uow)


@router.post("/{retrospective_id}/ai-drafts", response_model=AiDraftOut)
def create_ai_draft(
    retrospective_id: str,
    payload: AiDraftIn,
    actor: ActorDep,
    conf: SettingsDep,
) -> AiDraftOut:
    _enabled(conf)
    from app.services import retrospective_ai

    try:
        return AiDraftOut(
            **retrospective_ai.generate_isolated(
                retrospective_id=retrospective_id,
                expected_lock_version=payload.lock_version,
                actor=actor,
                settings=conf,
            )
        )
    except Exception as exc:
        _raise(exc)


def _action_out(record: RetrospectiveRecord, uow) -> RetrospectiveOut:
    return _record_out(record, _get_thesis(uow, record), uow)


@router.post("/{retrospective_id}/submit", response_model=RetrospectiveOut)
def submit(
    retrospective_id: str, payload: SubmitIn, actor: ActorDep, conf: SettingsDep, uow: UowDep
) -> RetrospectiveOut:
    _enabled(conf)
    try:
        return _action_out(
            retrospective_service.submit(
                uow,
                retrospective_id=retrospective_id,
                reviewer=payload.reviewer,
                expected_lock_version=payload.lock_version,
                actor=actor,
            ),
            uow,
        )
    except Exception as exc:
        _raise(exc)


@router.post("/{retrospective_id}/return", response_model=RetrospectiveOut)
def return_for_revision(
    retrospective_id: str,
    payload: ReasonActionIn,
    actor: ActorDep,
    conf: SettingsDep,
    uow: UowDep,
) -> RetrospectiveOut:
    _enabled(conf)
    try:
        return _action_out(
            retrospective_service.return_for_revision(
                uow,
                retrospective_id=retrospective_id,
                reason=payload.reason,
                expected_lock_version=payload.lock_version,
                actor=actor,
            ),
            uow,
        )
    except Exception as exc:
        _raise(exc)


@router.post("/{retrospective_id}/publish", response_model=RetrospectiveOut)
def publish(
    retrospective_id: str,
    payload: PublishIn,
    actor: ActorDep,
    conf: SettingsDep,
    uow: UowDep,
) -> RetrospectiveOut:
    _enabled(conf)
    try:
        return _action_out(
            retrospective_service.publish(
                uow,
                retrospective_id=retrospective_id,
                publish_reason=payload.publish_reason,
                expected_lock_version=payload.lock_version,
                actor=actor,
            ),
            uow,
        )
    except Exception as exc:
        _raise(exc)


@router.post("/{retrospective_id}/revisions", response_model=RetrospectiveOut)
def revise(
    retrospective_id: str,
    payload: ReasonActionIn,
    actor: ActorDep,
    conf: SettingsDep,
    uow: UowDep,
) -> RetrospectiveOut:
    _enabled(conf)
    try:
        return _action_out(
            retrospective_service.start_revision(
                uow,
                retrospective_id=retrospective_id,
                reason=payload.reason,
                expected_lock_version=payload.lock_version,
                actor=actor,
            ),
            uow,
        )
    except Exception as exc:
        _raise(exc)


@router.post("/{retrospective_id}/archive", response_model=RetrospectiveOut)
def archive(
    retrospective_id: str,
    payload: ReasonActionIn,
    actor: ActorDep,
    conf: SettingsDep,
    uow: UowDep,
) -> RetrospectiveOut:
    _enabled(conf)
    try:
        return _action_out(
            retrospective_service.archive(
                uow,
                retrospective_id=retrospective_id,
                reason=payload.reason,
                expected_lock_version=payload.lock_version,
                actor=actor,
            ),
            uow,
        )
    except Exception as exc:
        _raise(exc)


@router.get("/{retrospective_id}/exports/{format}")
def export(
    retrospective_id: str,
    format: str,
    actor: ActorDep,
    conf: SettingsDep,
    uow: UowDep,
) -> Response:
    _enabled(conf)
    try:
        body, media_type, filename = retrospective_service.export_published(
            uow,
            retrospective_id=retrospective_id,
            format=format,
            actor=actor,
            settings=conf,
        )
    except Exception as exc:
        _raise(exc)
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
