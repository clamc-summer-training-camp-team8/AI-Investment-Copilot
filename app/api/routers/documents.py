"""可核验原文段落读取接口。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import ActorDep, UowDep
from app.schemas.job import DocumentFullOut, DocumentSegmentOut
from app.services import document as document_service
from app.services.errors import NotVisible

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("/{document_id}", response_model=DocumentFullOut)
def get_full_document(document_id: str, actor: ActorDep, uow: UowDep) -> DocumentFullOut:
    """读取完整解析正文，供研报、财报、公告等材料的全文核验。"""
    try:
        document, segments = document_service.get_full_document(
            uow, document_id=document_id, actor=actor
        )
    except NotVisible as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DocumentFullOut(
        document_id=document.document_id,
        title=document.title,
        doc_type=document.doc_type,
        published_at=document.published_at,
        parser_version=document.parser_version,
        segment_count=len(segments),
        segments=[
            DocumentSegmentOut(
                document_id=document.document_id,
                title=document.title,
                locator=item.locator,
                ordinal=item.ordinal,
                page=item.page,
                content=item.content,
                content_kind=item.content_kind,
                extraction_method=item.extraction_method,
                table_index=item.table_index,
                row_index=item.row_index,
                cell_range=item.cell_range,
                confidence=float(item.confidence) if item.confidence is not None else None,
            )
            for item in segments
        ],
    )


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
