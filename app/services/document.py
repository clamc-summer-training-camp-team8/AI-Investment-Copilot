"""文档知识底座服务：原文、段落与正文事实原子持久化。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.core.domain import (
    DocumentFactRecord,
    DocumentRecord,
    DocumentSegmentRecord,
    UnitOfWork,
)
from app.ingest.facts import ExtractedFact
from app.ingest.segmentation import Segment
from app.services import audit
from app.services.errors import NotVisible, ValidationFailed
from app.services.permission import Actor


def persist_processed(
    uow: UnitOfWork,
    *,
    document_id: str,
    title: str | None,
    doc_type: str | None,
    published_at: datetime | None,
    content_hash: str | None,
    parser_version: str | None,
    segments: list[Segment],
    path: Path,
    actor: Actor,
    security_id: str | None,
    facts: list[ExtractedFact],
    visibility_label: str = "内部",
    raw_location: str | None = None,
) -> DocumentRecord:
    """持久化解析成功的文档；同内容重复上传返回既有文档并留审计。"""
    if published_at is None or content_hash is None:
        raise ValidationFailed("只有通过质量校验且披露时间完整的文档可以入库")
    if parser_version is None:
        raise ValidationFailed("解析器版本缺失，无法持久化文档")

    duplicate = uow.documents.find_by_content_hash(content_hash, parser_version)
    if duplicate is not None:
        audit.record(
            uow.audit,
            actor=actor.user_id,
            action="跳过重复文档",
            object_type="document",
            object_id=duplicate.document_id,
            detail={"uploaded_document_id": document_id},
        )
        return duplicate

    record = DocumentRecord(
        document_id=document_id,
        title=title,
        doc_type=doc_type,
        security_id=security_id,
        published_at=published_at,
        content_hash=content_hash,
        parser_version=parser_version,
        raw_path=raw_location or str(path),
        body="\n".join(segment.content for segment in segments),
        content_status="完整正文",
        visibility_label=visibility_label,
    )
    uow.documents.add(
        record,
        [
            DocumentSegmentRecord(
                document_id=item.document_id,
                locator=item.locator,
                ordinal=item.ordinal,
                page=item.page,
                content=item.content,
                content_kind=item.content_kind,
                extraction_method=item.extraction_method,
                table_index=item.table_index,
                row_index=item.row_index,
                cell_range=item.cell_range,
                confidence=item.confidence,
            )
            for item in segments
        ],
        [
            DocumentFactRecord(
                fact_id=item.fact_id,
                document_id=item.document_id,
                locator=item.locator,
                fact_type=item.fact_type,
                metric_name=item.metric_name,
                direction=item.direction,
                change_rate_low=item.change_rate_low,
                change_rate_high=item.change_rate_high,
                raw_text=item.raw_text,
                extraction_version=item.extraction_version,
            )
            for item in facts
        ],
    )
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action="文档入库",
        object_type="document",
        object_id=record.document_id,
        detail={
            "segment_count": len(segments),
            "fact_count": len(facts),
            "parser_version": record.parser_version,
        },
    )
    return record


def get_segment(
    uow: UnitOfWork, *, document_id: str, ordinal: int, actor: Actor
) -> tuple[DocumentRecord, DocumentSegmentRecord, str | None, str | None]:
    document = uow.documents.get(document_id)
    if (
        document is None
        or document.deleted_at is not None
        or document.visibility_label not in actor.document_labels
    ):
        raise NotVisible("文档不存在或无访问权限")
    segments = uow.documents.list_segments(document_id)
    for index, segment in enumerate(segments):
        if segment.ordinal != ordinal:
            continue
        previous_locator = segments[index - 1].locator if index > 0 else None
        next_locator = segments[index + 1].locator if index + 1 < len(segments) else None
        return document, segment, previous_locator, next_locator
    raise NotVisible("原文段落不存在或无访问权限")


def get_full_document(
    uow: UnitOfWork, *, document_id: str, actor: Actor
) -> tuple[DocumentRecord, list[DocumentSegmentRecord]]:
    """返回研究员有权限查看的完整解析文档，不暴露底层原文件存储路径。"""
    document = uow.documents.get(document_id)
    if (
        document is None
        or document.deleted_at is not None
        or document.visibility_label not in actor.document_labels
    ):
        raise NotVisible("文档不存在或无访问权限")
    return document, uow.documents.list_segments(document_id)
