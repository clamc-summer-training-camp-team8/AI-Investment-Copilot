"""证券主数据与结构化事件仓储。"""

from __future__ import annotations

import hashlib

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.domain import EventRecord, SecurityRecord
from app.db.models.core import Document, Event, MarketSecurity, Security
from app.db.models.coverage import MarketSector


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
                    func.coalesce(Security.industry, "").ilike(pattern),
                    cast(Security.aliases, String).ilike(pattern),
                )
            )
        rows = self._session.scalars(statement.order_by(Security.security_id).limit(limit)).all()
        return [_security(row) for row in rows]

    def search_market(self, keyword: str, *, limit: int = 100) -> list[SecurityRecord]:
        pattern = f"%{keyword}%"
        rows = self._session.scalars(
            select(MarketSecurity)
            .where(
                or_(
                    MarketSecurity.security_id.ilike(pattern),
                    MarketSecurity.name.ilike(pattern),
                    MarketSecurity.ticker.ilike(pattern),
                )
            )
            .order_by(MarketSecurity.security_id)
            .limit(limit)
        ).all()
        return [
            SecurityRecord(
                security_id=row.security_id,
                name=row.name,
                ticker=row.ticker,
                industry=row.industry,
                aliases=[str(item) for item in (row.aliases or [])],
            )
            for row in rows
        ]

    def upsert_market(self, record: SecurityRecord) -> None:
        sector_id = None
        if record.industry:
            sector_name = record.industry.split("-", 1)[0].strip() or "未分类"
            sector_id = f"MSEC-{hashlib.md5(sector_name.encode('utf-8')).hexdigest()}"
            self._session.execute(
                insert(MarketSector)
                .values(market_sector_id=sector_id, name=sector_name, source="market_security")
                .on_conflict_do_nothing(index_elements=[MarketSector.name])
            )
        values = {
            "security_id": record.security_id,
            "name": record.name,
            "ticker": record.ticker,
            "industry": record.industry,
            "market_sector_id": sector_id,
            "aliases": record.aliases,
            "source": "market",
        }
        statement = insert(MarketSecurity).values(**values)
        self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[MarketSecurity.security_id],
                set_={
                    "name": statement.excluded.name,
                    "ticker": statement.excluded.ticker,
                    "industry": statement.excluded.industry,
                    "market_sector_id": func.coalesce(statement.excluded.market_sector_id, MarketSecurity.market_sector_id),
                    "aliases": statement.excluded.aliases,
                    "source": statement.excluded.source,
                },
            )
        )
        self._session.flush()


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

    def search(
        self,
        keyword: str,
        *,
        visibility_labels: tuple[str, ...],
        published_to=None,
        limit: int = 20,
    ) -> list[EventRecord]:
        if not keyword.strip() or not visibility_labels:
            return []
        pattern = f"%{keyword.strip()}%"
        statement = (
            select(Event)
            .join(Document, Document.document_id == Event.document_id)
            .where(
                Document.deleted_at.is_(None),
                Document.visibility_label.in_(visibility_labels),
                or_(
                    Event.summary.ilike(pattern),
                    Event.event_type.ilike(pattern),
                    Event.security_id.ilike(pattern),
                ),
            )
        )
        if published_to is not None:
            statement = statement.where(Event.disclosure_time <= published_to)
        rows = self._session.scalars(
            statement.order_by(Event.disclosure_time.desc(), Event.event_id).limit(limit)
        ).all()
        return [_event(row) for row in rows]
