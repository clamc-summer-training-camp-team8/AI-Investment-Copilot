"""知识库 AI 问答路由。"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Response

from app.ai.errors import ModelUnavailable
from app.api.deps import ActorDep, SettingsDep, UowDep
from app.schemas.assistant import (
    AnswerCitationOut,
    AnswerFeedbackIn,
    KnowledgeAnswerIn,
    KnowledgeAnswerOut,
)
from app.services import knowledge_assistant
from app.services.errors import CitationInvalid, NotVisible, ValidationFailed

router = APIRouter(prefix="/assistant", tags=["assistant"])
_ANSWER_ID = re.compile(r"^ANS-[a-f0-9]{32}$")


@router.post("/answers", response_model=KnowledgeAnswerOut)
def answer_question(
    payload: KnowledgeAnswerIn,
    actor: ActorDep,
    conf: SettingsDep,
    uow: UowDep,
) -> KnowledgeAnswerOut:
    if not conf.knowledge_qa_enabled:
        raise HTTPException(
            status_code=404,
            detail={"code": "KNOWLEDGE_QA_DISABLED", "message": "知识库问答当前未启用"},
        )
    try:
        result = knowledge_assistant.answer(
            uow,
            question=payload.question,
            actor=actor,
            settings=conf,
            thesis_id=payload.context.thesis_id,
            security_id=payload.context.security_id,
            as_of=payload.context.as_of,
            history=[item.model_dump() for item in payload.history],
        )
    except NotVisible as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "ASSISTANT_CONTEXT_NOT_VISIBLE",
                "message": "研究上下文不存在或无访问权限",
            },
        ) from exc
    except CitationInvalid as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "ASSISTANT_CITATION_INVALID", "message": str(exc)},
        ) from exc
    except ValidationFailed as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "ASSISTANT_OUTPUT_INVALID", "message": str(exc)},
        ) from exc
    except ModelUnavailable as exc:
        status = 504 if "超过" in str(exc) else 503
        code = "ASSISTANT_MODEL_TIMEOUT" if status == 504 else "ASSISTANT_MODEL_UNAVAILABLE"
        raise HTTPException(
            status_code=status,
            detail={"code": code, "message": str(exc)},
        ) from exc
    return KnowledgeAnswerOut(
        answer_id=result.answer_id,
        answer_status=result.answer_status,
        ai_status=result.ai_status,
        answer=result.answer,
        inferences=result.inferences,
        citations=[AnswerCitationOut.model_validate(item.__dict__) for item in result.citations],
        model_version=result.model_version,
        prompt_version=result.prompt_version,
        retrieval_version=result.retrieval_version,
        graph_snapshot_id=result.graph_snapshot_id,
        generated_at=result.generated_at,
        request_id=result.request_id,
    )


@router.post("/answers/{answer_id}/feedback", status_code=204)
def answer_feedback(
    answer_id: str,
    payload: AnswerFeedbackIn,
    actor: ActorDep,
    conf: SettingsDep,
    uow: UowDep,
) -> Response:
    if not conf.knowledge_qa_enabled:
        raise HTTPException(
            status_code=404,
            detail={"code": "KNOWLEDGE_QA_DISABLED", "message": "知识库问答当前未启用"},
        )
    if not _ANSWER_ID.fullmatch(answer_id):
        raise HTTPException(
            status_code=404,
            detail={
                "code": "ASSISTANT_ANSWER_NOT_VISIBLE",
                "message": "回答不存在或无访问权限",
            },
        )
    knowledge_assistant.record_feedback(
        uow,
        answer_id=answer_id,
        value=payload.value,
        reason=payload.reason,
        actor=actor,
    )
    return Response(status_code=204)
