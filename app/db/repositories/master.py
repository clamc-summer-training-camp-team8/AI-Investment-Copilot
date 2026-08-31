"""证券主数据与结构化事件仓储。"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.domain import EventRecord, SecurityRecord
from app.db.models.core import Event, Security


def _security(row: Security) -> SecurityRecord:
    return SecurityRecord(
        security_id=row.security_id,
        name=row.name,
        ticker=row.ticker,
        industry=row.industry,
        aliases=[str(item) for item in (row.aliases or [])],
        is_illustrative=row.is_illustrative,
    )


def _event(row: Event) -> EventRecord:
    return EventRecord(
        event_id=row.event_id,
        document_id=row.document_id,
        security_id=row.security_id,
        event_type=row.event_type,
        summary=row.summary,
        occurred_on=row.occurred_on,
        disclosure_time=row.disclosure_time,
        fingerprint=row.fingerprint,
        source_document_ids=[str(item) for item in (row.source_document_ids or [])],
        version=row.version,
        is_illustrative=row.is_illustrative,
    )


class SqlSecurityRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, security_id: str) -> SecurityRecord | None:
        row = self._session.get(Security, security_id)
        return None if row is None else _security(row)

    def add(self, record: SecurityRecord) -> None:
        self._session.add(
            Security(
                security_id=record.security_id,
                name=record.name,
                ticker=record.ticker,
                industry=record.industry,
                aliases=record.aliases,
                is_illustrative=record.is_illustrative,
            )
        )
        self._session.flush()

    def search(self, keyword: str | None = None, *, limit: int = 100) -> list[SecurityRecord]:
        statement = select(Security)
        if keyword:
            pattern = f"%{keyword}%"
            statement = statement.where(
                or_(
                    Security.security_id.ilike(pattern),
                    Security.name.ilike(pattern),
                    Security.ticker.ilike(pattern),
                )
            )
        rows = self._session.scalars(statement.order_by(Security.security_id).limit(limit)).all()
        return [_security(row) for row in rows]


class SqlEventRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, event_id: str) -> EventRecord | None:
        row = self._session.get(Event, event_id)
        return None if row is None else _event(row)

    def find_by_fingerprint(self, fingerprint: str) -> EventRecord | None:
        row = self._session.scalar(select(Event).where(Event.fingerprint == fingerprint))
        return None if row is None else _event(row)

    def add(self, record: EventRecord) -> None:
        self._session.add(
            Event(
                event_id=record.event_id,
                document_id=record.document_id,
                security_id=record.security_id,
                event_type=record.event_type,
                summary=record.summary,
                occurred_on=record.occurred_on,
                disclosure_time=record.disclosure_time,
                fingerprint=record.fingerprint,
                source_document_ids=record.source_document_ids,
                version=record.version,
                is_illustrative=record.is_illustrative,
            )
        )
        self._session.flush()

    def update(self, record: EventRecord) -> None:
        row = self._session.get(Event, record.event_id)
        if row is None:
            raise LookupError(f"event {record.event_id} 不存在")
        row.source_document_ids = record.source_document_ids
        self._session.flush()
