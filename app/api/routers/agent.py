"""Agent 后端编排接口。

接口只返回或保存候选，不提供任何绕过人工确认发布正式结果的路径。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.ai.errors import ModelUnavailable
from app.api.deps import ActorDep, SettingsDep, UowDep
from app.schemas.agent import (
    AgentCandidateOut,
    MetricRecommendationIn,
    ReviewDraftIn,
    RevisionCandidateOut,
)
from app.schemas.assets import ThesisRevisionOut
from app.services import agent_workflow
from app.services.errors import HumanGateRequired, NotVisible, ValidationFailed

router = APIRouter(prefix="/agent", tags=["agent"])


def _candidate_out(candidate: agent_workflow.AgentCandidate) -> AgentCandidateOut:
    return AgentCandidateOut(
        run_id=candidate.run_id,
        task=candidate.task,
        status=candidate.status,
        ai_status=candidate.ai_status,
        requires_human_review=candidate.requires_human_review,
        payload=candidate.payload,
        errors=list(candidate.errors),
    )


def _raise_http(exc: Exception) -> None:
    if isinstance(exc, NotVisible):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, HumanGateRequired):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, ModelUnavailable):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/theses/{thesis_id}/hypotheses/{hypothesis_id}/metric-recommendations",
    response_model=AgentCandidateOut,
)
def recommend_metrics(
    thesis_id: str,
    hypothesis_id: str,
    payload: MetricRecommendationIn,
    actor: ActorDep,
    conf: SettingsDep,
    uow: UowDep,
) -> AgentCandidateOut:
    try:
        candidate = agent_workflow.recommend_metrics(
            uow,
            thesis_id=thesis_id,
            hypothesis_id=hypothesis_id,
            actor=actor,
            settings=conf,
            top_k=payload.top_k,
            as_of=payload.as_of,
        )
    except (NotVisible, HumanGateRequired, ModelUnavailable, ValidationFailed, ValueError) as exc:
        _raise_http(exc)
    return _candidate_out(candidate)


@router.post(
    "/theses/{thesis_id}/hypotheses/{hypothesis_id}/metric-explanations",
    response_model=AgentCandidateOut,
)
def explain_metric(
    thesis_id: str,
    hypothesis_id: str,
    actor: ActorDep,
    conf: SettingsDep,
    uow: UowDep,
) -> AgentCandidateOut:
    try:
        candidate = agent_workflow.explain_metric_results(
            uow,
            thesis_id=thesis_id,
            hypothesis_id=hypothesis_id,
            actor=actor,
            settings=conf,
        )
    except (NotVisible, HumanGateRequired, ModelUnavailable, ValidationFailed, ValueError) as exc:
        _raise_http(exc)
    return _candidate_out(candidate)


@router.post("/theses/{thesis_id}/review-drafts", response_model=AgentCandidateOut)
def create_review_draft(
    thesis_id: str,
    payload: ReviewDraftIn,
    actor: ActorDep,
    conf: SettingsDep,
    uow: UowDep,
) -> AgentCandidateOut:
    try:
        candidate = agent_workflow.draft_review(
            uow,
            thesis_id=thesis_id,
            period_start=payload.period_start,
            period_end=payload.period_end,
            actor=actor,
            settings=conf,
        )
    except (NotVisible, HumanGateRequired, ModelUnavailable, ValidationFailed, ValueError) as exc:
        _raise_http(exc)
    return _candidate_out(candidate)


@router.post("/theses/{thesis_id}/revision-drafts", response_model=RevisionCandidateOut)
def create_revision_draft(
    thesis_id: str,
    actor: ActorDep,
    conf: SettingsDep,
    uow: UowDep,
) -> RevisionCandidateOut:
    try:
        result = agent_workflow.draft_revision(
            uow,
            thesis_id=thesis_id,
            actor=actor,
            settings=conf,
        )
    except (NotVisible, HumanGateRequired, ModelUnavailable, ValidationFailed, ValueError) as exc:
        _raise_http(exc)
    return RevisionCandidateOut(
        execution=_candidate_out(result.execution),
        revision=ThesisRevisionOut.model_validate(result.revision),
    )
