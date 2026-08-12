"""可核验原文段落读取接口。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import ActorDep, UowDep
from app.schemas.job import DocumentSegmentOut
from app.services import document as document_service
from app.services.errors import NotVisible

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("/{document_id}/segments/{ordinal}", response_model=DocumentSegmentOut)
def get_document_segment(
    document_id: str, ordinal: int, actor: ActorDep, uow: UowDep
) -> DocumentSegmentOut:
    try:
        document, segment, previous_locator, next_locator = document_service.get_segment(
            uow, document_id=document_id, ordinal=ordinal, actor=actor
        )
    except NotVisible as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DocumentSegmentOut(
        document_id=document.document_id,
        title=document.title,
        locator=segment.locator,
        ordinal=segment.ordinal,
        page=segment.page,
        content=segment.content,
        content_kind=segment.content_kind,
        extraction_method=segment.extraction_method,
        table_index=segment.table_index,
        row_index=segment.row_index,
        cell_range=segment.cell_range,
        confidence=float(segment.confidence) if segment.confidence is not None else None,
        previous_locator=previous_locator,
        next_locator=next_locator,
    )
