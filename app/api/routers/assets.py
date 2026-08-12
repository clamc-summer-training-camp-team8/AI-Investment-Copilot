"""Research asset inventory, reprocessing and post-publication revision endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response

from app.api.deps import ActorDep, SettingsDep, UowDep
from app.schemas.assets import (
    AssetInventoryOut,
    AssetSearchHitOut,
    DocumentVisibilityIn,
    ReprocessIn,
    SearchRebuildOut,
    ThesisRevisionDiffOut,
    ThesisRevisionOut,
    ThesisRevisionPublishIn,
    ThesisRevisionUpdateIn,
)
from app.services import assets as asset_service
from app.services.errors import HumanGateRequired, NotVisible, ValidationFailed
from app.workers.queue import QueueUnavailable, enqueue_job_record, open_queue, worker_ready

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("/inventory", response_model=AssetInventoryOut)
def inventory(actor: ActorDep, uow: UowDep) -> AssetInventoryOut:
    result = uow.assets.inventory()
    return AssetInventoryOut(**result)


@router.post("/search-index/rebuild", response_model=SearchRebuildOut)
def rebuild_search_index(actor: ActorDep, uow: UowDep) -> SearchRebuildOut:
    if "analyst-mvp" not in actor.teams and "asset-admin" not in actor.teams:
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
