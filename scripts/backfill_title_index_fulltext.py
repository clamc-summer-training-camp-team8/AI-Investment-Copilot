"""Promote archived title-index documents to searchable full text.

The job is deliberately append-oriented and resumable:

* only active ``标题索引`` documents with an authorized archived revision are selected;
* the existing canonical title segment and its locator are never changed;
* parsed full-text segments receive locators after the current maximum ordinal;
* one ingestion run, its immutable artifacts, canonical projections, search projection and
  audit record are committed in the same transaction;
* a parse or duplicate-content failure appends a failed run without changing the document.

Document-to-thesis linkage is deterministic at this stage: the confirmed document-security
relation is joined to the single current thesis for that security.  This is lineage metadata,
not an automatically confirmed evidence-to-hypothesis judgment.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.core.config import PROJECT_ROOT, settings
from app.core.domain import IngestionArtifactRecord, IngestionRunRecord
from app.db.models.assets import DocumentRevision, DocumentSecurityRelation
from app.db.models.core import Document, DocumentFact, DocumentSegment, Thesis
from app.db.models.governance import AuditLog
from app.db.repositories.assets import SqlAssetRepo
from app.db.session import engine, session_scope
from app.ingest.facts import EXTRACTION_VERSION, extract_key_facts
from app.ingest.parsers.base import PARSER_VERSION
from app.ingest.segmentation import Segment, build_locator
from app.services.object_store import S3ObjectStore
from app.workers.document_chain import DocumentResult, process_document

CHUNKER_VERSION = "paragraph-v2-preserve-title"
EXTRACTOR_VERSION = f"{EXTRACTION_VERSION}+thesis-link-v1"
EMBEDDING_VERSION = "hash-char-2gram-v1"
AUTHORIZED_STATUSES = frozenset({"公开披露已核验", "用户授权上传", "项目自有"})
DEFAULT_REPORT = PROJECT_ROOT / ".runtime" / "governance" / "title-index-fulltext.json"
_THREAD_LOCAL = threading.local()


@dataclass(frozen=True)
class Candidate:
    document_id: str
    published_at: datetime
    revision_id: str
    object_key: str
    object_version_id: str | None
    source_filename: str
    media_type: str | None
    authorization_status: str
    security_id: str
    thesis_id: str


@dataclass(frozen=True)
class ParsedCandidate:
    candidate: Candidate
    result: DocumentResult


@dataclass(frozen=True)
class ItemOutcome:
    document_id: str
    status: str
    run_id: str | None = None
    segment_count: int = 0
    fact_count: int = 0
    thesis_id: str | None = None
    error: str | None = None


def remap_segments(
    document_id: str, segments: list[Segment], *, after_ordinal: int
) -> list[Segment]:
    """Assign collision-free locators while preserving parsed segment order and metadata."""
    return [
        Segment(
            document_id=document_id,
            locator=build_locator(document_id, after_ordinal + index),
            ordinal=after_ordinal + index,
            content=segment.content,
            page=segment.page,
            content_kind=segment.content_kind,
            extraction_method=segment.extraction_method,
            table_index=segment.table_index,
            row_index=segment.row_index,
            cell_range=segment.cell_range,
            confidence=segment.confidence,
        )
        for index, segment in enumerate(segments, start=1)
    ]


def _candidates(*, limit: int | None, document_id: str | None) -> list[Candidate]:
    """Return one latest authorized archived revision per active title-index document."""
    with session_scope() as session:
        statement = (
            select(Document, DocumentRevision, DocumentSecurityRelation, Thesis)
            .join(
                DocumentRevision,
                DocumentRevision.canonical_document_id == Document.document_id,
            )
            .join(
                DocumentSecurityRelation,
                DocumentSecurityRelation.document_id == Document.document_id,
            )
            .join(
                Thesis,
                (Thesis.security_id == DocumentSecurityRelation.security_id)
                & Thesis.is_current.is_(True),
            )
            .where(
                Document.content_status == "标题索引",
                Document.deleted_at.is_(None),
                DocumentRevision.object_key.is_not(None),
                DocumentRevision.tombstoned_at.is_(None),
                DocumentRevision.authorization_status.in_(AUTHORIZED_STATUSES),
                DocumentSecurityRelation.status == "已确认",
            )
            .order_by(
                Document.document_id,
                DocumentRevision.created_at.desc(),
                DocumentRevision.revision_id.desc(),
            )
            .distinct(Document.document_id)
        )
        if document_id:
            statement = statement.where(Document.document_id == document_id)
        if limit is not None:
            statement = statement.limit(limit)
        return [
            Candidate(
                document_id=document.document_id,
                published_at=document.published_at,
                revision_id=revision.revision_id,
                object_key=str(revision.object_key),
                object_version_id=revision.object_version_id,
                source_filename=revision.source_filename,
                media_type=revision.media_type,
                authorization_status=revision.authorization_status,
                security_id=relation.security_id,
                thesis_id=thesis.thesis_id,
            )
            for document, revision, relation, thesis in session.execute(statement)
        ]


def _object_store() -> S3ObjectStore:
    store = getattr(_THREAD_LOCAL, "object_store", None)
    if store is None:
        store = S3ObjectStore(settings)
        _THREAD_LOCAL.object_store = store
    return store


def _suffix(candidate: Candidate) -> str:
    suffix = Path(candidate.source_filename).suffix.lower()
    if suffix in {".pdf", ".docx", ".txt"}:
        return suffix
    if candidate.media_type == "application/pdf":
        return ".pdf"
    if candidate.media_type in {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }:
        return ".docx"
    if candidate.media_type and candidate.media_type.startswith("text/"):
        return ".txt"
    return suffix or ".bin"


def _parse(candidate: Candidate, destination: Path) -> ParsedCandidate:
    target = destination / f"{candidate.document_id}-{uuid4().hex}{_suffix(candidate)}"
    try:
        _object_store().download(
            object_key=candidate.object_key,
            version_id=candidate.object_version_id,
            destination=target,
        )
        result = process_document(
            document_id=candidate.document_id,
            path=target,
            published_at=candidate.published_at,
        )
        return ParsedCandidate(candidate, result)
    except Exception as exc:  # preserve every operational failure in an ingestion run
        return ParsedCandidate(
            candidate,
            DocumentResult(
                document_id=candidate.document_id,
                ok=False,
                segments=[],
                parser_version=PARSER_VERSION,
                failure_reason=f"{type(exc).__name__}: {exc}",
            ),
        )
    finally:
        target.unlink(missing_ok=True)


def _artifact(
    run_id: str, artifact_type: str, artifact_key: str, payload: dict[str, Any]
) -> IngestionArtifactRecord:
    normalized = _json(payload)
    encoded = json.dumps(
        normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return IngestionArtifactRecord(
        run_id=run_id,
        artifact_type=artifact_type,
        artifact_key=artifact_key,
        payload=normalized,
        content_hash=sha256(encoded).hexdigest(),
    )


def _json(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json(item) for item in value]
    return value


def _add_failed_run(candidate: Candidate, reason: str) -> ItemOutcome:
    run_id = f"IRUN-FULL-{uuid4().hex}"
    timestamp = datetime.now(UTC)
    with session_scope() as session:
        SqlAssetRepo(session).add_run(
            IngestionRunRecord(
                run_id=run_id,
                revision_id=candidate.revision_id,
                parser_version=PARSER_VERSION,
                chunker_version=CHUNKER_VERSION,
                extractor_version=EXTRACTOR_VERSION,
                embedding_version=EMBEDDING_VERSION,
                status="failed",
                quality_summary={
                    "source_content_status": "标题索引",
                    "authorization_status": candidate.authorization_status,
                    "canonical_segments_preserved": True,
                },
                error=reason[:8000],
                started_at=timestamp,
                finished_at=timestamp,
            )
        )
    return ItemOutcome(
        document_id=candidate.document_id,
        status="failed",
        run_id=run_id,
        thesis_id=candidate.thesis_id,
        error=reason,
    )


def _persist(parsed: ParsedCandidate) -> ItemOutcome:
    candidate, result = parsed.candidate, parsed.result
    if not result.ok or not result.segments or not result.content_hash:
        return _add_failed_run(candidate, result.failure_reason or "未解析出可用正文")

    run_id = f"IRUN-FULL-{uuid4().hex}"
    timestamp = datetime.now(UTC)
    with session_scope() as session:
        document = session.scalar(
            select(Document).where(Document.document_id == candidate.document_id).with_for_update()
        )
        if document is None:
            return ItemOutcome(candidate.document_id, "skipped", error="文档不存在")
        if document.content_status != "标题索引":
            return ItemOutcome(candidate.document_id, "skipped", error="文档已由其他运行处理")

        parser_version = result.parser_version or PARSER_VERSION
        duplicate_id = session.scalar(
            select(Document.document_id).where(
                Document.document_id != candidate.document_id,
                Document.content_hash == result.content_hash,
                Document.parser_version == parser_version,
                Document.deleted_at.is_(None),
            )
        )
        if duplicate_id:
            # Roll back this transaction by returning before any mutation, then append a failed run
            # outside it. session_scope will still commit a no-op transaction.
            duplicate_reason = f"完整正文与现有文档 {duplicate_id} 重复，需人工归并"
        else:
            duplicate_reason = None

        if duplicate_reason is None:
            existing_rows = list(
                session.scalars(
                    select(DocumentSegment)
                    .where(DocumentSegment.document_id == candidate.document_id)
                    .order_by(DocumentSegment.ordinal, DocumentSegment.id)
                )
            )
            max_ordinal = max((item.ordinal for item in existing_rows), default=0)
            full_segments = remap_segments(
                candidate.document_id,
                result.segments,
                after_ordinal=max_ordinal,
            )
            facts = extract_key_facts(full_segments)

            for segment in full_segments:
                session.add(DocumentSegment(**asdict(segment)))
            for fact in facts:
                session.add(DocumentFact(**asdict(fact)))

            revision = session.get(DocumentRevision, candidate.revision_id)
            if revision is None or revision.tombstoned_at is not None:
                raise RuntimeError("活动原件 revision 在解析期间失效")
            revision.content_status = "完整正文"

            document.body = "\n".join(segment.content for segment in result.segments)
            document.content_hash = result.content_hash
            document.parser_version = parser_version
            document.content_status = "完整正文"
            if not document.doc_type and result.doc_type:
                document.doc_type = result.doc_type

            repo = SqlAssetRepo(session)
            repo.add_run(
                IngestionRunRecord(
                    run_id=run_id,
                    revision_id=candidate.revision_id,
                    parser_version=parser_version,
                    chunker_version=CHUNKER_VERSION,
                    extractor_version=EXTRACTOR_VERSION,
                    embedding_version=EMBEDDING_VERSION,
                    status="succeeded",
                    segment_count=len(existing_rows) + len(full_segments),
                    fact_count=len(facts),
                    quality_summary={
                        "promoted_from": "标题索引",
                        "authorization_status": candidate.authorization_status,
                        "preserved_segment_count": len(existing_rows),
                        "fulltext_segment_count": len(full_segments),
                        "canonical_segments_preserved": True,
                        "security_relation_status": "已确认",
                        "thesis_relation_basis": "security_current_thesis",
                        "formal_evidence_created": False,
                    },
                    started_at=timestamp,
                    finished_at=timestamp,
                )
            )

            all_segments = [
                Segment(
                    document_id=row.document_id,
                    locator=row.locator,
                    ordinal=row.ordinal,
                    content=row.content,
                    page=row.page,
                    content_kind=row.content_kind,
                    extraction_method=row.extraction_method,
                    table_index=row.table_index,
                    row_index=row.row_index,
                    cell_range=row.cell_range,
                    confidence=row.confidence,
                )
                for row in existing_rows
            ] + full_segments
            artifacts = [
                _artifact(run_id, "segment", segment.locator, asdict(segment))
                for segment in all_segments
            ]
            artifacts.extend(
                _artifact(run_id, "fact", fact.fact_id, asdict(fact)) for fact in facts
            )
            artifacts.append(
                _artifact(
                    run_id,
                    "thesis_relation",
                    candidate.thesis_id,
                    {
                        "document_id": candidate.document_id,
                        "security_id": candidate.security_id,
                        "thesis_id": candidate.thesis_id,
                        "relation_type": "security_current_thesis",
                        "status": "已确认",
                        "evidence_confirmation_status": "未生成",
                    },
                )
            )
            repo.add_artifacts(artifacts)
            repo.remove_document_from_index(candidate.document_id)
            repo.index_artifacts(
                run_id=run_id,
                document_id=candidate.document_id,
                visibility_label=document.visibility_label,
                records=artifacts,
            )
            session.add(
                AuditLog(
                    actor="system:title-fulltext-backfill",
                    action="标题索引提升为完整正文",
                    object_type="document",
                    object_id=candidate.document_id,
                    detail={
                        "run_id": run_id,
                        "revision_id": candidate.revision_id,
                        "security_id": candidate.security_id,
                        "thesis_id": candidate.thesis_id,
                        "fulltext_segment_count": len(full_segments),
                        "fact_count": len(facts),
                        "preserved_locators": [row.locator for row in existing_rows],
                        "formal_evidence_created": False,
                    },
                )
            )
            return ItemOutcome(
                document_id=candidate.document_id,
                status="succeeded",
                run_id=run_id,
                segment_count=len(full_segments),
                fact_count=len(facts),
                thesis_id=candidate.thesis_id,
            )

    return _add_failed_run(candidate, duplicate_reason or "未知持久化错误")


def _persist_with_retry(parsed: ParsedCandidate, *, attempts: int = 4) -> ItemOutcome:
    """Retry transient database disconnects without reparsing the archived source."""
    last_error: OperationalError | None = None
    for attempt in range(1, attempts + 1):
        try:
            return _persist(parsed)
        except OperationalError as exc:
            last_error = exc
            engine.dispose()
            if attempt < attempts:
                time.sleep(min(2**attempt, 10))
    assert last_error is not None
    raise last_error


def _record_unhandled_failure(candidate: Candidate, exc: Exception) -> ItemOutcome:
    reason = f"{type(exc).__name__}: {exc}"
    for attempt in range(1, 4):
        try:
            return _add_failed_run(candidate, reason)
        except OperationalError:
            engine.dispose()
            if attempt < 3:
                time.sleep(min(2**attempt, 10))
    return ItemOutcome(
        document_id=candidate.document_id,
        status="failed_unrecorded",
        thesis_id=candidate.thesis_id,
        error=reason,
    )


def _configure_local_no_proxy() -> None:
    endpoint = settings.object_store_endpoint
    if not endpoint:
        return
    from urllib.parse import urlparse

    host = urlparse(endpoint).hostname
    if not host:
        return
    for key in ("NO_PROXY", "no_proxy"):
        values = [item.strip() for item in os.environ.get(key, "").split(",") if item.strip()]
        for item in (host, "localhost", "127.0.0.1", "::1"):
            if item not in values:
                values.append(item)
        os.environ[key] = ",".join(values)


def _report_payload(
    *, started_at: datetime, candidates: list[Candidate], outcomes: list[ItemOutcome], dry_run: bool
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for item in outcomes:
        counts[item.status] = counts.get(item.status, 0) + 1
    return {
        "schema_version": "title-index-fulltext-report-v1",
        "started_at": started_at.isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
        "dry_run": dry_run,
        "candidate_count": len(candidates),
        "counts": counts,
        "fulltext_segments": sum(item.segment_count for item in outcomes),
        "facts": sum(item.fact_count for item in outcomes),
        "items": [asdict(item) for item in outcomes],
    }


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for attempt in range(1, 11):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 10:
                raise
            time.sleep(attempt / 10)


def backfill(
    *,
    limit: int | None = None,
    document_id: str | None = None,
    workers: int = 4,
    batch_size: int = 24,
    dry_run: bool = False,
    report_path: Path = DEFAULT_REPORT,
) -> dict[str, Any]:
    _configure_local_no_proxy()
    started_at = datetime.now(UTC)
    candidates = _candidates(limit=limit, document_id=document_id)
    outcomes: list[ItemOutcome] = []
    if dry_run:
        outcomes = [
            ItemOutcome(item.document_id, "eligible", thesis_id=item.thesis_id)
            for item in candidates
        ]
        payload = _report_payload(
            started_at=started_at, candidates=candidates, outcomes=outcomes, dry_run=True
        )
        _write_report(report_path, payload)
        return payload

    with TemporaryDirectory(prefix="copilot-title-fulltext-") as temp:
        destination = Path(temp)
        iterator = iter(candidates)
        window_size = max(max(1, workers) * 2, max(1, batch_size))
        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            futures: dict[Future[ParsedCandidate], Candidate] = {}

            def submit_next() -> bool:
                try:
                    candidate = next(iterator)
                except StopIteration:
                    return False
                futures[executor.submit(_parse, candidate, destination)] = candidate
                return True

            for _ in range(min(window_size, len(candidates))):
                submit_next()

            while futures:
                completed, _ = wait(futures, return_when=FIRST_COMPLETED)
                for future in completed:
                    candidate = futures.pop(future)
                    try:
                        outcomes.append(_persist_with_retry(future.result()))
                    except Exception as exc:
                        outcomes.append(_record_unhandled_failure(candidate, exc))
                    submit_next()
                if len(outcomes) % max(1, batch_size) < len(completed):
                    _write_report(
                        report_path,
                        _report_payload(
                            started_at=started_at,
                            candidates=candidates,
                            outcomes=outcomes,
                            dry_run=False,
                        ),
                    )
        _write_report(
            report_path,
            _report_payload(
                started_at=started_at,
                candidates=candidates,
                outcomes=outcomes,
                dry_run=False,
            ),
        )
    return _report_payload(
        started_at=started_at,
        candidates=candidates,
        outcomes=outcomes,
        dry_run=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--document-id")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=24)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    payload = backfill(
        limit=args.limit,
        document_id=args.document_id,
        workers=args.workers,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        report_path=args.report,
    )
    print(
        json.dumps(
            {key: value for key, value in payload.items() if key != "items"}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
