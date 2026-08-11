"""Researcher review-center endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import ActorDep, UowDep
from app.core.domain import ReviewTaskRecord
from app.schemas.review import ReviewTaskCreateIn, ReviewTaskOut, ReviewTaskResolveIn
from app.services import review as review_service
from app.services.errors import NotVisible, ValidationFailed

router = APIRouter(prefix="/reviews", tags=["reviews"])


def _out(record: ReviewTaskRecord) -> ReviewTaskOut:
    return ReviewTaskOut(**record.__dict__)


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
