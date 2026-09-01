"""主投资逻辑当日归并结果的持久化。"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.domain import LogicChangeDigestRecord
from app.core.enums import ConfirmationStatus
from app.db.models.core import LogicChangeDigest


def _to_record(row: LogicChangeDigest) -> LogicChangeDigestRecord:
    return LogicChangeDigestRecord(
        digest_id=row.digest_id,
        security_id=row.security_id,
        thesis_id=row.thesis_id,
        business_date=row.business_date,
        overall_direction=row.overall_direction,
        summary=row.summary,
        hypothesis_impacts=list(row.hypothesis_impacts or []),
        open_questions=list(row.open_questions or []),
        citations=list(row.citations or []),
        source_document_ids=list(row.source_document_ids or []),
        candidate_count=row.candidate_count,
        confidence=row.confidence,
        ai_status=row.ai_status,
        confirmation_status=ConfirmationStatus(row.confirmation_status),
        model_version=row.model_version,
        prompt_version=row.prompt_version,
        generated_at=row.generated_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlLogicChangeDigestRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_scope(
        self, *, security_id: str, thesis_id: str, business_date: date
    ) -> LogicChangeDigestRecord | None:
        row = self._session.scalar(
            select(LogicChangeDigest).where(
                LogicChangeDigest.security_id == security_id,
                LogicChangeDigest.thesis_id == thesis_id,
                LogicChangeDigest.business_date == business_date,
            )
        )
        return _to_record(row) if row else None

    def upsert(self, record: LogicChangeDigestRecord) -> LogicChangeDigestRecord:
        row = self._session.scalar(
            select(LogicChangeDigest).where(
                LogicChangeDigest.security_id == record.security_id,
                LogicChangeDigest.thesis_id == record.thesis_id,
                LogicChangeDigest.business_date == record.business_date,
            )
        )
        if row is None:
            row = LogicChangeDigest(
                digest_id=record.digest_id,
                security_id=record.security_id,
                thesis_id=record.thesis_id,
                business_date=record.business_date,
                overall_direction=record.overall_direction,
                summary=record.summary,
                hypothesis_impacts=record.hypothesis_impacts,
                open_questions=record.open_questions,
                citations=record.citations,
                source_document_ids=record.source_document_ids,
                candidate_count=record.candidate_count,
                confidence=record.confidence,
                ai_status=record.ai_status,
                confirmation_status=record.confirmation_status.value,
                model_version=record.model_version,
                prompt_version=record.prompt_version,
                generated_at=record.generated_at,
            )
            self._session.add(row)
        else:
            row.overall_direction = record.overall_direction
            row.summary = record.summary
            row.hypothesis_impacts = record.hypothesis_impacts
            row.open_questions = record.open_questions
            row.citations = record.citations
            row.source_document_ids = record.source_document_ids
            row.candidate_count = record.candidate_count
            row.confidence = record.confidence
            row.ai_status = record.ai_status
            row.model_version = record.model_version
            row.prompt_version = record.prompt_version
            row.generated_at = record.generated_at
        self._session.flush()
        return _to_record(row)

    def list_for_security(
        self, *, security_id: str, limit: int = 30
    ) -> list[LogicChangeDigestRecord]:
        rows = self._session.scalars(
            select(LogicChangeDigest)
            .where(LogicChangeDigest.security_id == security_id)
            .order_by(LogicChangeDigest.business_date.desc(), LogicChangeDigest.updated_at.desc())
            .limit(limit)
        ).all()
        return [_to_record(row) for row in rows]

    def list_for_business_day(self, *, business_date: date) -> list[LogicChangeDigestRecord]:
        rows = self._session.scalars(
            select(LogicChangeDigest)
            .where(LogicChangeDigest.business_date == business_date)
            .order_by(LogicChangeDigest.updated_at.desc())
        ).all()
        return [_to_record(row) for row in rows]
