"""Researcher review-center endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import ActorDep, SettingsDep, UowDep
from app.core.domain import IngestionReviewRecord, ReviewTaskRecord
from app.schemas.review import (
    IngestionReviewOut,
    IngestionReviewResolveIn,
    ReviewTaskCreateIn,
    ReviewTaskOut,
    ReviewTaskResolveIn,
)
from app.services import ingestion as ingestion_service
from app.services import review as review_service
from app.services.errors import NotVisible, ValidationFailed
from app.workers.queue import QueueUnavailable, enqueue_job_record, open_queue, worker_ready

router = APIRouter(prefix="/reviews", tags=["reviews"])


def _out(record: ReviewTaskRecord) -> ReviewTaskOut:
    return ReviewTaskOut(**record.__dict__)


def _ingestion_out(record: IngestionReviewRecord) -> IngestionReviewOut:
    return IngestionReviewOut(
        review_id=record.review_id,
        review_type=record.review_type,
        document_id=record.document_id,
        job_id=record.job_id,
        event_id=record.event_id,
        reason=record.reason,
        status=record.status,
        payload=record.payload,
        security_candidates=record.security_candidates,
        resolution=record.resolution,
        created_at=record.created_at,
        resolved_at=record.resolved_at,
    )


@router.get("/ingestion", response_model=list[IngestionReviewOut])
def list_ingestion_reviews(
    actor: ActorDep,
    uow: UowDep,
    status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[IngestionReviewOut]:
    return [
        _ingestion_out(record)
        for record in ingestion_service.list_reviews(uow, actor=actor, status=status, limit=limit)
    ]


@router.post("/ingestion/{review_id}/resolve", response_model=IngestionReviewOut)
async def resolve_ingestion_review(
    review_id: str,
    payload: IngestionReviewResolveIn,
    actor: ActorDep,
    conf: SettingsDep,
    uow: UowDep,
) -> IngestionReviewOut:
    try:
        record = ingestion_service.resolve_review(
            uow,
            review_id=review_id,
            actor=actor,
            resolution=payload.resolution,
            security_id=payload.security_id,
        )
        source = None
        if payload.security_id and record.job_id:
            source = ingestion_service.get_job(uow, job_id=record.job_id, actor=actor)
    except NotVisible as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationFailed as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if source is not None and payload.security_id is not None:
        redis = None
        try:
            redis = await open_queue(conf)
            if not await worker_ready(redis):
                raise QueueUnavailable("任务处理器不可用，请先启动 ARQ worker")
            replay = ingestion_service.build_assignment_replay(
                uow, source=source, security_id=payload.security_id, actor=actor
            )
            await enqueue_job_record(redis, replay)
        except QueueUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        finally:
            if redis is not None:
                await redis.aclose()
    return _ingestion_out(record)


@router.get("", response_model=list[ReviewTaskOut])
def list_reviews(
    actor: ActorDep,
    uow: UowDep,
    state: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[ReviewTaskOut]:
    return [
        _out(record)
        for record in review_service.list_assigned(uow, actor=actor, state=state, limit=limit)
    ]


@router.get("/{task_id}", response_model=ReviewTaskOut)
def get_review(task_id: str, actor: ActorDep, uow: UowDep) -> ReviewTaskOut:
    try:
        return _out(review_service.get_assigned(uow, task_id=task_id, actor=actor))
    except NotVisible as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("", response_model=ReviewTaskOut, status_code=201)
def create_review(payload: ReviewTaskCreateIn, actor: ActorDep, uow: UowDep) -> ReviewTaskOut:
    assignee = payload.assignee or actor.user_id
    if assignee != actor.user_id:
        raise HTTPException(status_code=403, detail="MVP 只允许创建分配给自己的复核任务")
    try:
        return _out(
            review_service.create_task(
                uow,
                thesis_id=payload.thesis_id,
                trigger=payload.trigger,
                priority=payload.priority,
                assignee=assignee,
                actor=actor,
                detail=payload.detail,
            )
        )
    except NotVisible as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationFailed as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{task_id}/resolve", response_model=ReviewTaskOut)
def resolve_review(
    task_id: str,
    payload: ReviewTaskResolveIn,
    actor: ActorDep,
    uow: UowDep,
) -> ReviewTaskOut:
    try:
        return _out(
            review_service.resolve(
                uow,
                task_id=task_id,
                actor=actor,
                resolution=payload.resolution,
            )
        )
    except NotVisible as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationFailed as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
