"""固定真实案例 Demo API。"""

from __future__ import annotations

from typing import Annotated, Literal, NoReturn

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from app.api.deps import ActorDep
from app.schemas.demo import (
    CitationContextOut,
    DemoUploadOut,
    EvidenceAnalysisOut,
    HypothesisHealthOut,
    TimelinePageOut,
)
from app.services import demo as demo_service
from app.services.errors import NotVisible, ValidationFailed

router = APIRouter(tags=["demo"])


def _raise_service_error(exc: Exception) -> NoReturn:
    if isinstance(exc, demo_service.DemoFileMismatch):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, NotVisible):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, ValidationFailed):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


@router.post(
    "/demo/theses/{thesis_id}/documents",
    response_model=DemoUploadOut,
    summary="Upload Fixed Demo Material",
)
async def upload_demo_material(
    thesis_id: str,
    actor: ActorDep,
    file: Annotated[UploadFile, File(...)],
    demo_case_id: Annotated[str, Form(...)],
) -> DemoUploadOut:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="上传文件为空")
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="固定演示资料不得超过 15MB")
    try:
        result = demo_service.upload_material(
            thesis_id=thesis_id,
            demo_case_id=demo_case_id,
            filename=file.filename or "annual-report.pdf",
            content=content,
            actor=actor,
        )
    except Exception as exc:
        _raise_service_error(exc)
    return DemoUploadOut.model_validate(result)


@router.get(
    "/evidence/{evidence_id}/analysis",
    response_model=EvidenceAnalysisOut,
    summary="Get Preset Evidence Analysis",
)
def get_evidence_analysis(
    evidence_id: str,
    relation_id: str,
    actor: ActorDep,
) -> EvidenceAnalysisOut:
    try:
        result = demo_service.get_analysis(
            evidence_id=evidence_id,
            relation_id=relation_id,
            actor=actor,
        )
    except Exception as exc:
        _raise_service_error(exc)
    return EvidenceAnalysisOut.model_validate(result)


@router.get(
    "/documents/{document_id}/citation",
    response_model=CitationContextOut,
    summary="Get Document Citation Context",
)
def get_document_citation(
    document_id: str,
    locator: str,
    actor: ActorDep,
) -> CitationContextOut:
    try:
        result = demo_service.get_citation(
            document_id=document_id,
            locator=locator,
            actor=actor,
        )
    except Exception as exc:
        _raise_service_error(exc)
    return CitationContextOut.model_validate(result)


@router.get(
    "/theses/{thesis_id}/hypothesis-health",
    response_model=list[HypothesisHealthOut],
    summary="Get Derived Hypothesis Health",
)
def get_hypothesis_health(
    thesis_id: str,
    actor: ActorDep,
) -> list[HypothesisHealthOut]:
    try:
        result = demo_service.get_hypothesis_health(thesis_id=thesis_id, actor=actor)
    except Exception as exc:
        _raise_service_error(exc)
    return [HypothesisHealthOut.model_validate(item) for item in result]


@router.get(
    "/theses/{thesis_id}/timeline",
    response_model=TimelinePageOut,
    summary="Get Structured Thesis Timeline",
)
def get_thesis_timeline(
    thesis_id: str,
    actor: ActorDep,
    dimension: Literal[
        "material",
        "ai_analysis",
        "human_review",
        "hypothesis_health",
        "logic_decision",
    ]
    | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    order: Literal["asc"] = "asc",
) -> TimelinePageOut:
    del order
    try:
        result = demo_service.get_timeline(
            thesis_id=thesis_id,
            actor=actor,
            dimension=dimension,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        _raise_service_error(exc)
    return TimelinePageOut.model_validate(result)
