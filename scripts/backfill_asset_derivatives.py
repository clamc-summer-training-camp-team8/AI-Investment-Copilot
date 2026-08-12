"""Append semantic chunks/facts/events for legacy bodies without replacing old runs."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import exists, select

from app.core.domain import IngestionArtifactRecord, IngestionRunRecord
from app.db.models.assets import DocumentRevision, IngestionRun
from app.db.models.core import Document, Event
from app.db.repositories.assets import SqlAssetRepo
from app.db.session import session_scope
from app.ingest.facts import extract_key_facts
from app.ingest.semantic_chunking import semantic_chunks


def backfill(*, limit: int | None = None) -> dict[str, int]:
    processed = skipped = segments_total = facts_total = events_total = 0
    with session_scope() as session:
        statement = (
            select(Document, DocumentRevision)
            .join(DocumentRevision, DocumentRevision.canonical_document_id == Document.document_id)
            .where(
                Document.body.is_not(None),
                Document.deleted_at.is_(None),
                ~exists().where(
                    IngestionRun.revision_id == DocumentRevision.revision_id,
                    IngestionRun.chunker_version == "semantic-v1",
                    IngestionRun.status == "succeeded",
                ),
            )
            .order_by(Document.document_id)
        )
        if limit is not None:
            statement = statement.limit(limit)
        repo = SqlAssetRepo(session)
        for document, revision in session.execute(statement):
            chunks = semantic_chunks(document.document_id, document.body or "")
            if not chunks:
                skipped += 1
                continue
            facts = extract_key_facts(chunks)
            events = session.scalars(
                select(Event).where(Event.document_id == document.document_id)
            ).all()
            run_id = f"IRUN-SEM-{uuid4().hex}"
            timestamp = datetime.now(UTC)
            repo.add_run(
                IngestionRunRecord(
                    run_id=run_id,
                    revision_id=revision.revision_id,
                    parser_version=document.parser_version,
                    chunker_version="semantic-v1",
                    extractor_version="body-facts-v1+event-v1",
                    status="succeeded",
                    segment_count=len(chunks),
                    fact_count=len(facts),
                    event_count=len(events),
                    quality_summary={
                        "backfilled_from": "document.body",
                        "source_archive_missing": revision.object_key is None,
                        "authorization_pending": revision.authorization_status == "待确认",
                        "canonical_segments_preserved": True,
                    },
                    started_at=timestamp,
                    finished_at=timestamp,
                )
            )
            artifacts = [
                _artifact(run_id, "segment", item.locator, asdict(item)) for item in chunks
            ]
            artifacts.extend(
                _artifact(run_id, "fact", item.fact_id, asdict(item)) for item in facts
            )
            artifacts.extend(
                _artifact(
                    run_id,
                    "event",
                    item.event_id,
                    {
                        "event_id": item.event_id,
                        "document_id": item.document_id,
                        "security_id": item.security_id,
                        "event_type": item.event_type,
                        "summary": item.summary,
                        "occurred_on": item.occurred_on,
                        "disclosure_time": item.disclosure_time,
                        "fingerprint": item.fingerprint,
                        "source_document_ids": item.source_document_ids or [],
                        "version": item.version,
                    },
                )
                for item in events
            )
            repo.add_artifacts(artifacts)
            repo.index_artifacts(
                run_id=run_id,
                document_id=document.document_id,
                visibility_label=document.visibility_label,
                records=artifacts,
            )
            processed += 1
            segments_total += len(chunks)
            facts_total += len(facts)
            events_total += len(events)
    return {
        "processed_documents": processed,
        "skipped_documents": skipped,
        "semantic_segments": segments_total,
        "facts": facts_total,
        "events": events_total,
    }


def _artifact(
    run_id: str, artifact_type: str, artifact_key: str, payload: dict
) -> IngestionArtifactRecord:
    normalized = {key: _json(value) for key, value in payload.items()}
    digest = sha256(repr(sorted(normalized.items())).encode()).hexdigest()
    return IngestionArtifactRecord(run_id, artifact_type, artifact_key, normalized, digest)


def _json(value):
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    print(backfill(limit=args.limit))


if __name__ == "__main__":
    main()
