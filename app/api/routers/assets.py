"""Research asset inventory, reprocessing and post-publication revision endpoints."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Response
from fastapi.responses import FileResponse

from app.api.deps import ActorDep, SettingsDep, UowDep
from app.schemas.assets import (
    AssetDocumentDetailOut,
    AssetDocumentOut,
    AssetDocumentPageOut,
    AssetInventoryOut,
    AssetOverviewOut,
    AssetRevisionOut,
    AssetRunOut,
    AssetRunPageOut,
    AssetSearchHitOut,
    AssetSourceOut,
    DocumentVisibilityIn,
    ReprocessIn,
    RestoreDocumentIn,
    SearchRebuildOut,
    ThesisRevisionDiffOut,
    ThesisRevisionOut,
    ThesisRevisionPublishIn,
    ThesisRevisionUpdateIn,
)
from app.services import assets as asset_service
from app.services.errors import HumanGateRequired, NotVisible, ValidationFailed
from app.services.object_store import ObjectStoreError, S3ObjectStore
from app.workers.queue import QueueUnavailable, enqueue_job_record, open_queue, worker_ready

router = APIRouter(prefix="/assets", tags=["assets"])


def _run_out(record) -> AssetRunOut:
    return AssetRunOut.model_validate(record)


def _revision_out(record) -> AssetRevisionOut:
    host = urlparse(record.source_url).hostname if record.source_url else None
    return AssetRevisionOut(
        revision_id=record.revision_id,
        content_hash=record.content_hash,
        source_filename=record.source_filename,
        has_object=record.object_key is not None,
        object_version_id=record.object_version_id,
        media_type=record.media_type,
        byte_size=record.byte_size,
        source_id=record.source_id,
        source_host=host,
        authorization_status=record.authorization_status,
        authorization_basis=record.authorization_basis,
        authorization_verified_by=record.authorization_verified_by,
        authorization_verified_at=record.authorization_verified_at,
        content_status=record.content_status,
        uploaded_by=record.uploaded_by,
        published_at=record.published_at,
        created_at=record.created_at,
        tombstoned_at=record.tombstoned_at,
    )


@router.get("/inventory", response_model=AssetInventoryOut)
def inventory(actor: ActorDep, uow: UowDep) -> AssetInventoryOut:
    result = uow.assets.inventory()
    return AssetInventoryOut(**result)


@router.get("/overview", response_model=AssetOverviewOut)
def overview(actor: ActorDep, uow: UowDep) -> AssetOverviewOut:
    return AssetOverviewOut.model_validate(asset_service.data_center_overview(uow, actor=actor))


@router.get("/documents", response_model=AssetDocumentPageOut)
def list_documents(
    actor: ActorDep,
    uow: UowDep,
    q: str | None = Query(default=None, max_length=200),
    content_status: str | None = None,
    source_id: str | None = None,
    doc_type: str | None = None,
    security_id: str | None = None,
    industry: str | None = None,
    authorization_status: str | None = None,
    archived: bool | None = None,
    run_status: str | None = None,
    visibility_label: str | None = None,
    published_from: datetime | None = None,
    published_to: datetime | None = None,
    include_deleted: bool = False,
    sort: str = "published_at",
    direction: str = "desc",
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> AssetDocumentPageOut:
    try:
        records, total = asset_service.list_document_catalog(
            uow,
            actor=actor,
            query=q,
            content_status=content_status,
            source_id=source_id,
            doc_type=doc_type,
            security_id=security_id,
            industry=industry,
            authorization_status=authorization_status,
            archived=archived,
            run_status=run_status,
            visibility_label=visibility_label,
            published_from=published_from,
            published_to=published_to,
            include_deleted=include_deleted,
            sort=sort,
            direction=direction,
            limit=limit,
            offset=offset,
        )
    except HumanGateRequired as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValidationFailed as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AssetDocumentPageOut(
        items=[AssetDocumentOut.model_validate(item) for item in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/documents/{document_id}", response_model=AssetDocumentDetailOut)
def get_document(
    document_id: str,
    actor: ActorDep,
    uow: UowDep,
    include_deleted: bool = False,
) -> AssetDocumentDetailOut:
    try:
        record, revisions, runs, actions = asset_service.get_document_catalog(
            uow,
            document_id=document_id,
            actor=actor,
            include_deleted=include_deleted,
        )
    except NotVisible as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AssetDocumentDetailOut(
        **AssetDocumentOut.model_validate(record).model_dump(),
        allowed_actions=actions,
        revisions=[_revision_out(item) for item in revisions],
        runs=[_run_out(item) for item in runs],
    )


@router.get("/documents/{document_id}/revisions", response_model=list[AssetRevisionOut])
def list_document_revisions(
    document_id: str, actor: ActorDep, uow: UowDep
) -> list[AssetRevisionOut]:
    try:
        _, revisions, _, _ = asset_service.get_document_catalog(
            uow, document_id=document_id, actor=actor
        )
    except NotVisible as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [_revision_out(item) for item in revisions]


@router.get("/documents/{document_id}/ingestion-runs", response_model=list[AssetRunOut])
def list_document_runs(document_id: str, actor: ActorDep, uow: UowDep) -> list[AssetRunOut]:
    try:
        _, _, runs, _ = asset_service.get_document_catalog(
            uow, document_id=document_id, actor=actor
        )
    except NotVisible as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [_run_out(item) for item in runs]


@router.get("/documents/{document_id}/content", response_class=FileResponse)
def get_document_content(
    document_id: str,
    background_tasks: BackgroundTasks,
    actor: ActorDep,
    conf: SettingsDep,
    uow: UowDep,
    download: bool = False,
) -> FileResponse:
    try:
        _, revision = asset_service.get_document_content_revision(
            uow, document_id=document_id, actor=actor
        )
        assert revision.object_key is not None
        source_name = Path(revision.source_filename.replace("\\", "/")).name[:255]
        suffix = Path(source_name).suffix[:16]
        with NamedTemporaryFile(delete=False, suffix=suffix) as temporary:
            target = Path(temporary.name)
        S3ObjectStore(conf).download(
            object_key=revision.object_key,
            version_id=revision.object_version_id,
            destination=target,
        )
    except NotVisible as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationFailed as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ObjectStoreError as exc:
        if "target" in locals():
            target.unlink(missing_ok=True)
        raise HTTPException(status_code=503, detail="归档原件暂时不可用") from exc
    background_tasks.add_task(target.unlink, missing_ok=True)
    safe_inline_types = {"application/pdf", "text/plain"}
    disposition = (
        "attachment" if download or revision.media_type not in safe_inline_types else "inline"
    )
    return FileResponse(
        target,
        media_type=revision.media_type or "application/octet-stream",
        filename=source_name or f"{document_id}{suffix}",
        content_disposition_type=disposition,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        background=background_tasks,
    )


@router.get("/sources", response_model=list[AssetSourceOut])
def list_sources(actor: ActorDep, uow: UowDep) -> list[AssetSourceOut]:
    return [
        AssetSourceOut.model_validate(item)
        for item in asset_service.list_data_sources(uow, actor=actor)
    ]


@router.get("/ingestion-runs", response_model=AssetRunPageOut)
def list_ingestion_runs(
    actor: ActorDep,
    uow: UowDep,
    status: str | None = None,
    document_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> AssetRunPageOut:
    try:
        records, total = asset_service.list_data_runs(
            uow,
            actor=actor,
            status=status,
            document_id=document_id,
            limit=limit,
            offset=offset,
        )
    except ValidationFailed as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AssetRunPageOut(
        items=[_run_out(item) for item in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/search-index/rebuild", response_model=SearchRebuildOut)
def rebuild_search_index(actor: ActorDep, uow: UowDep) -> SearchRebuildOut:
    if not asset_service.can_operate_assets(actor):
        raise HTTPException(status_code=403, detail="只有资产管理员可以重建检索索引")
    return SearchRebuildOut(indexed_segments=uow.assets.rebuild_search_index())


@router.get("/search", response_model=list[AssetSearchHitOut])
def search_assets(
    actor: ActorDep,
    uow: UowDep,
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[AssetSearchHitOut]:
    return [
        AssetSearchHitOut.model_validate(item)
        for item in asset_service.search_assets(uow, query=q, actor=actor, limit=limit)
    ]


@router.get("/hybrid-search", response_model=list[AssetSearchHitOut])
def hybrid_search_assets(
    actor: ActorDep,
    conf: SettingsDep,
    uow: UowDep,
    q: str = Query(min_length=1, max_length=200),
    security_id: Annotated[list[str] | None, Query()] = None,
    industry: Annotated[list[str] | None, Query()] = None,
    published_from: Annotated[datetime | None, Query()] = None,
    published_to: Annotated[datetime | None, Query()] = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[AssetSearchHitOut]:
    """P1 pilot: filtered hybrid retrieval, returned as candidate context only."""
    try:
        return [
            AssetSearchHitOut.model_validate(item)
            for item in asset_service.hybrid_retrieve(
                uow,
                query=q,
                actor=actor,
                settings=conf,
                security_ids=tuple(security_id or ()),
                industries=tuple(industry or ()),
                published_from=published_from,
                published_to=published_to,
                limit=limit,
            )
        ]
    except ValidationFailed as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/documents/{document_id}/visibility", status_code=204)
def update_document_visibility(
    document_id: str,
    payload: DocumentVisibilityIn,
    actor: ActorDep,
    uow: UowDep,
) -> Response:
    try:
        asset_service.change_document_visibility(
            uow,
            document_id=document_id,
            visibility_label=payload.visibility_label,
            actor=actor,
        )
        return Response(status_code=204)
    except HumanGateRequired as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except NotVisible as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationFailed as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/documents/{document_id}", status_code=204)
def delete_document_asset(document_id: str, actor: ActorDep, uow: UowDep) -> Response:
    try:
        asset_service.tombstone_document(uow, document_id=document_id, actor=actor)
        return Response(status_code=204)
    except HumanGateRequired as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except NotVisible as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/documents/{document_id}/restore", response_model=SearchRebuildOut)
def restore_document_asset(
    document_id: str,
    payload: RestoreDocumentIn,
    actor: ActorDep,
    uow: UowDep,
) -> SearchRebuildOut:
    try:
        indexed = asset_service.restore_document(
            uow,
            document_id=document_id,
            visibility_label=payload.visibility_label,
            actor=actor,
        )
        return SearchRebuildOut(indexed_segments=indexed)
    except HumanGateRequired as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except NotVisible as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationFailed as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/ingestion-runs/reprocess", status_code=202)
async def reprocess_document(
    payload: ReprocessIn, actor: ActorDep, conf: SettingsDep, uow: UowDep
) -> dict[str, str]:
    redis = None
    try:
        redis = await open_queue(conf)
        if not await worker_ready(redis):
            raise QueueUnavailable("任务处理器不可用，请先启动 ARQ worker")
        job = asset_service.create_reprocessing_job(
            uow, document_id=payload.document_id, actor=actor, settings=conf
        )
        await enqueue_job_record(redis, job)
        return {"job_id": job.job_id, "document_id": job.document_id}
    except NotVisible as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationFailed as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except QueueUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        if redis is not None:
            await redis.aclose()


@router.post("/theses/{thesis_id}/revisions", response_model=ThesisRevisionOut, status_code=201)
def create_thesis_revision(thesis_id: str, actor: ActorDep, uow: UowDep) -> ThesisRevisionOut:
    try:
        return ThesisRevisionOut.model_validate(
            asset_service.create_thesis_revision(uow, thesis_id=thesis_id, actor=actor)
        )
    except NotVisible as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HumanGateRequired as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.patch("/thesis-revisions/{draft_id}", response_model=ThesisRevisionOut)
def update_thesis_revision(
    draft_id: str,
    payload: ThesisRevisionUpdateIn,
    actor: ActorDep,
    uow: UowDep,
) -> ThesisRevisionOut:
    try:
        return ThesisRevisionOut.model_validate(
            asset_service.update_thesis_revision(
                uow,
                draft_id=draft_id,
                expected_revision=payload.expected_revision,
                payload=payload.payload,
                actor=actor,
            )
        )
    except NotVisible as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationFailed as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/thesis-revisions/{draft_id}/diff", response_model=ThesisRevisionDiffOut)
def thesis_revision_diff(draft_id: str, actor: ActorDep, uow: UowDep) -> ThesisRevisionDiffOut:
    record = uow.assets.get_thesis_revision(draft_id)
    if record is None or record.owner != actor.user_id:
        raise HTTPException(status_code=404, detail="修订草稿不存在或无访问权限")
    base = uow.versions.latest(record.thesis_id)
    result = asset_service.revision_diff(record, base.snapshot if base else {})
    return ThesisRevisionDiffOut(**result)


@router.post("/thesis-revisions/{draft_id}/publish", response_model=ThesisRevisionOut)
def publish_thesis_revision(
    draft_id: str,
    payload: ThesisRevisionPublishIn,
    actor: ActorDep,
    conf: SettingsDep,
    uow: UowDep,
) -> ThesisRevisionOut:
    try:
        return ThesisRevisionOut.model_validate(
            asset_service.publish_thesis_revision(
                uow,
                draft_id=draft_id,
                expected_revision=payload.expected_revision,
                reason=payload.reason,
                actor=actor,
                settings=conf,
            )
        )
    except NotVisible as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValidationFailed, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
