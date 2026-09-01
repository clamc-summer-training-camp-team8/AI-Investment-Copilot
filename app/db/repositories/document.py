"""文档、段落与正文事实仓储。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.domain import DocumentFactRecord, DocumentRecord, DocumentSegmentRecord
from app.db.models.core import Document, DocumentFact, DocumentSegment


def _document(row: Document) -> DocumentRecord:
    return DocumentRecord(
        document_id=row.document_id,
        title=row.title,
        source_id=row.source_id,
        doc_type=row.doc_type,
        security_id=row.security_id,
        published_at=row.published_at,
        ingested_at=row.ingested_at,
        content_hash=row.content_hash,
        parser_version=row.parser_version,
        raw_path=row.raw_path,
        body=row.body,
        visibility_label=row.visibility_label,
        content_status=row.content_status,
        is_illustrative=row.is_illustrative,
        deleted_at=row.deleted_at,
    )


class SqlDocumentRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, document_id: str) -> DocumentRecord | None:
        row = self._session.get(Document, document_id)
        return None if row is None else _document(row)

    def find_by_content_hash(self, content_hash: str, parser_version: str) -> DocumentRecord | None:
        row = self._session.scalar(
            select(Document).where(
                Document.content_hash == content_hash,
                Document.parser_version == parser_version,
            )
        )
        return None if row is None else _document(row)

    def add(
        self,
        record: DocumentRecord,
        segments: list[DocumentSegmentRecord],
        facts: list[DocumentFactRecord],
    ) -> None:
        self._session.add(
            Document(
                document_id=record.document_id,
                title=record.title,
                source_id=record.source_id,
                doc_type=record.doc_type,
                security_id=record.security_id,
                published_at=record.published_at,
                content_hash=record.content_hash,
                parser_version=record.parser_version,
                raw_path=record.raw_path,
                body=record.body,
                visibility_label=record.visibility_label,
                content_status=record.content_status,
                is_illustrative=record.is_illustrative,
            )
        )
        self._session.add_all(
            [
                DocumentSegment(
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
            ]
        )
        self._session.add_all(
            [
                DocumentFact(
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
            ]
        )
        self._session.flush()

    def update_security(self, document_id: str, security_id: str) -> None:
        row = self._session.get(Document, document_id)
        if row is None:
            raise LookupError(document_id)
        row.security_id = security_id
        self._session.flush()

    def update_visibility(self, document_id: str, visibility_label: str) -> None:
        row = self._session.get(Document, document_id)
        if row is None:
            raise LookupError(document_id)
        row.visibility_label = visibility_label
        self._session.flush()

    def mark_deleted(self, document_id: str, deleted_at: datetime) -> None:
        row = self._session.get(Document, document_id)
        if row is None:
            raise LookupError(document_id)
        row.deleted_at = deleted_at
        row.visibility_label = "已删除"
        self._session.flush()

    def restore(self, document_id: str, visibility_label: str) -> None:
        row = self._session.get(Document, document_id)
        if row is None:
            raise LookupError(document_id)
        row.deleted_at = None
        row.visibility_label = visibility_label
        self._session.flush()

    def list_segments(self, document_id: str) -> list[DocumentSegmentRecord]:
        rows = self._session.scalars(
            select(DocumentSegment)
            .where(DocumentSegment.document_id == document_id)
            .order_by(DocumentSegment.ordinal)
        ).all()
        return [
            DocumentSegmentRecord(
                document_id=row.document_id,
                locator=row.locator,
                ordinal=row.ordinal,
                page=row.page,
                content=row.content,
                content_kind=row.content_kind,
                extraction_method=row.extraction_method,
                table_index=row.table_index,
                row_index=row.row_index,
                cell_range=row.cell_range,
                confidence=row.confidence,
            )
            for row in rows
        ]

    def list_facts(self, document_id: str) -> list[DocumentFactRecord]:
        rows = self._session.scalars(
            select(DocumentFact)
            .where(DocumentFact.document_id == document_id)
            .order_by(DocumentFact.locator, DocumentFact.fact_type)
        ).all()
        return [
            DocumentFactRecord(
                fact_id=row.fact_id,
                document_id=row.document_id,
                locator=row.locator,
                fact_type=row.fact_type,
                metric_name=row.metric_name,
                direction=row.direction,
                change_rate_low=row.change_rate_low,
                change_rate_high=row.change_rate_high,
                raw_text=row.raw_text,
                extraction_version=row.extraction_version,
            )
            for row in rows
        ]
