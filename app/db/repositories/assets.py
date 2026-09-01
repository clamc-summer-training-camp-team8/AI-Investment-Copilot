"""Repositories for source lineage, immutable revisions and reprocessable artifacts."""

from __future__ import annotations

from urllib.parse import urlparse

from sqlalchemy import delete, exists, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.domain import (
    AssetDocumentRecord,
    AssetRunCatalogRecord,
    AssetSearchHitRecord,
    AssetSourceCatalogRecord,
    DocumentRevisionRecord,
    DocumentSecurityRelationRecord,
    EmbeddingSourceRecord,
    IndustryRecord,
    IngestionArtifactRecord,
    IngestionRunRecord,
    SecurityIndustryMembershipRecord,
    SegmentEmbeddingRecord,
    SourceRecord,
    ThesisRevisionDraftRecord,
)
from app.db.models.assets import (
    DocumentRevision,
    DocumentSecurityRelation,
    Industry,
    IngestionArtifact,
    IngestionRun,
    SecurityIndustryMembership,
    SegmentEmbedding,
    SegmentSearchIndex,
    Source,
    ThesisRevisionDraft,
)
from app.db.models.core import Document, DocumentFact, DocumentSegment

_BULK_WRITE_BATCH_SIZE = 4_000
_SEARCH_REBUILD_DOCUMENT_BATCH_SIZE = 100

_DOCUMENT_CATALOG_CTE = """
WITH related AS (
  SELECT dsr.document_id,
         array_agg(DISTINCT sec.security_id ORDER BY sec.security_id) AS security_ids,
         array_agg(DISTINCT sec.name ORDER BY sec.name) AS security_names,
         array_remove(array_agg(DISTINCT sec.industry ORDER BY sec.industry),NULL) AS industries
  FROM document_security_relation dsr
  JOIN security sec ON sec.security_id=dsr.security_id
  WHERE dsr.status='已确认'
  GROUP BY dsr.document_id
), catalog AS (
  SELECT d.document_id,
         COALESCE(NULLIF(BTRIM(d.title),''),d.document_id) AS title,
         d.source_id,
         COALESCE(NULLIF(BTRIM(src.name),''),NULLIF(BTRIM(d.source_id),''),'未登记来源') AS source_name,
         d.doc_type,d.published_at,d.ingested_at,d.content_status,d.visibility_label,
         d.is_illustrative,d.deleted_at,d.body AS search_body,
         EXISTS (
           SELECT 1 FROM document_revision rev
           WHERE COALESCE(rev.canonical_document_id,rev.document_id)=d.document_id
             AND rev.object_key IS NOT NULL AND rev.tombstoned_at IS NULL
         ) AS archived,
         COALESCE((
           SELECT rev.authorization_status FROM document_revision rev
           WHERE COALESCE(rev.canonical_document_id,rev.document_id)=d.document_id
             AND rev.tombstoned_at IS NULL
           ORDER BY (rev.object_key IS NOT NULL) DESC,rev.created_at DESC,rev.revision_id DESC
           LIMIT 1
         ),'待确认') AS authorization_status,
         (SELECT count(*)::int FROM document_revision rev
          WHERE COALESCE(rev.canonical_document_id,rev.document_id)=d.document_id) AS revision_count,
         (SELECT count(*)::int FROM document_segment seg
          WHERE seg.document_id=d.document_id) AS segment_count,
         (SELECT ir.status FROM ingestion_run ir
          JOIN document_revision rev ON rev.revision_id=ir.revision_id
          WHERE COALESCE(rev.canonical_document_id,rev.document_id)=d.document_id
          ORDER BY ir.created_at DESC,ir.run_id DESC LIMIT 1) AS latest_run_status,
         (SELECT COALESCE(ir.finished_at,ir.started_at,ir.created_at) FROM ingestion_run ir
          JOIN document_revision rev ON rev.revision_id=ir.revision_id
          WHERE COALESCE(rev.canonical_document_id,rev.document_id)=d.document_id
          ORDER BY ir.created_at DESC,ir.run_id DESC LIMIT 1) AS latest_run_at,
         COALESCE(rel.security_ids,ARRAY[]::text[]) AS security_ids,
         COALESCE(rel.security_names,ARRAY[]::text[]) AS security_names,
         COALESCE(rel.industries,ARRAY[]::text[]) AS industries
  FROM document d
  LEFT JOIN source src ON src.source_id=d.source_id
  LEFT JOIN related rel ON rel.document_id=d.document_id
  WHERE d.visibility_label=ANY(CAST(:labels AS text[]))
    AND (CAST(:include_deleted AS boolean) OR d.deleted_at IS NULL)
)
"""


def _catalog_record(row) -> AssetDocumentRecord:
    return AssetDocumentRecord(
        document_id=str(row["document_id"]),
        title=str(row["title"]),
        source_id=str(row["source_id"]) if row["source_id"] else None,
        source_name=str(row["source_name"]),
        doc_type=str(row["doc_type"]) if row["doc_type"] else None,
        published_at=row["published_at"],
        ingested_at=row["ingested_at"],
        content_status=str(row["content_status"]),
        visibility_label=str(row["visibility_label"]),
        is_illustrative=bool(row["is_illustrative"]),
        deleted_at=row["deleted_at"],
        archived=bool(row["archived"]),
        authorization_status=str(row["authorization_status"]),
        revision_count=int(row["revision_count"] or 0),
        segment_count=int(row["segment_count"] or 0),
        latest_run_status=str(row["latest_run_status"]) if row["latest_run_status"] else None,
        latest_run_at=row["latest_run_at"],
        security_ids=tuple(str(value) for value in (row["security_ids"] or [])),
        security_names=tuple(str(value) for value in (row["security_names"] or [])),
        industries=tuple(str(value) for value in (row["industries"] or [])),
    )


def _run_catalog_record(row) -> AssetRunCatalogRecord:
    return AssetRunCatalogRecord(
        run_id=str(row["run_id"]),
        revision_id=str(row["revision_id"]),
        document_id=str(row["document_id"]),
        document_title=str(row["document_title"]),
        source_filename=str(row["source_filename"]),
        parser_version=str(row["parser_version"]),
        chunker_version=str(row["chunker_version"]),
        extractor_version=str(row["extractor_version"]),
        embedding_version=str(row["embedding_version"]) if row["embedding_version"] else None,
        status=str(row["status"]),
        segment_count=int(row["segment_count"] or 0),
        fact_count=int(row["fact_count"] or 0),
        event_count=int(row["event_count"] or 0),
        quality_summary=dict(row["quality_summary"] or {}),
        error=str(row["error"]) if row["error"] else None,
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        created_at=row["created_at"],
    )


def _revision(row: DocumentRevision) -> DocumentRevisionRecord:
    return DocumentRevisionRecord(
        revision_id=row.revision_id,
        document_id=row.document_id,
        canonical_document_id=row.canonical_document_id,
        content_hash=row.content_hash,
        source_filename=row.source_filename,
        object_key=row.object_key,
        object_version_id=row.object_version_id,
        media_type=row.media_type,
        byte_size=row.byte_size,
        source_id=row.source_id,
        source_url=row.source_url,
        authorization_status=row.authorization_status,
        authorization_basis=row.authorization_basis,
        authorization_verified_by=row.authorization_verified_by,
        authorization_verified_at=row.authorization_verified_at,
        content_status=row.content_status,
        uploaded_by=row.uploaded_by,
        published_at=row.published_at,
        created_at=row.created_at,
        tombstoned_at=row.tombstoned_at,
    )


def _run(row: IngestionRun) -> IngestionRunRecord:
    return IngestionRunRecord(
        run_id=row.run_id,
        revision_id=row.revision_id,
        parser_version=row.parser_version,
        chunker_version=row.chunker_version,
        extractor_version=row.extractor_version,
        embedding_version=row.embedding_version,
        status=row.status,
        segment_count=row.segment_count,
        fact_count=row.fact_count,
        event_count=row.event_count,
        quality_summary=dict(row.quality_summary or {}),
        error=row.error,
        started_at=row.started_at,
        finished_at=row.finished_at,
        created_at=row.created_at,
    )


def _draft(row: ThesisRevisionDraft) -> ThesisRevisionDraftRecord:
    return ThesisRevisionDraftRecord(
        draft_id=row.draft_id,
        thesis_id=row.thesis_id,
        base_version=row.base_version,
        revision=row.revision,
        owner=row.owner,
        payload=dict(row.payload),
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlAssetRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_source(self, record: SourceRecord) -> None:
        self._session.add(Source(**record.__dict__))
        self._session.flush()

    def get_source(self, source_id: str) -> SourceRecord | None:
        row = self._session.get(Source, source_id)
        return (
            None
            if row is None
            else SourceRecord(
                source_id=row.source_id,
                name=row.name,
                source_type=row.source_type,
                authorization_status=row.authorization_status,
                base_url=row.base_url,
                license_note=row.license_note,
                active=row.active,
                authorization_basis=row.authorization_basis,
                authorization_verified_by=row.authorization_verified_by,
                authorization_verified_at=row.authorization_verified_at,
            )
        )

    def add_industry(self, record: IndustryRecord) -> None:
        self._session.add(Industry(**record.__dict__))
        self._session.flush()

    def get_industry_by_name(self, name: str) -> IndustryRecord | None:
        row = self._session.scalar(select(Industry).where(Industry.name == name))
        return None if row is None else IndustryRecord(row.industry_id, row.name, row.parent_id)

    def add_membership(self, record: SecurityIndustryMembershipRecord) -> None:
        self._session.add(SecurityIndustryMembership(**record.__dict__))
        self._session.flush()

    def add_document_security(self, record: DocumentSecurityRelationRecord) -> None:
        existing = self._session.scalar(
            select(DocumentSecurityRelation).where(
                DocumentSecurityRelation.document_id == record.document_id,
                DocumentSecurityRelation.security_id == record.security_id,
                DocumentSecurityRelation.relation_type == record.relation_type,
            )
        )
        if existing is None:
            self._session.add(DocumentSecurityRelation(**record.__dict__))
            self._session.flush()

    def add_revision(self, record: DocumentRevisionRecord) -> None:
        self._session.add(DocumentRevision(**record.__dict__))
        self._session.flush()

    def get_revision(self, revision_id: str) -> DocumentRevisionRecord | None:
        row = self._session.get(DocumentRevision, revision_id)
        return None if row is None else _revision(row)

    def find_revision_by_hash(self, content_hash: str) -> DocumentRevisionRecord | None:
        row = self._session.scalar(
            select(DocumentRevision)
            .where(DocumentRevision.content_hash == content_hash)
            .order_by(DocumentRevision.created_at, DocumentRevision.revision_id)
            .limit(1)
        )
        return None if row is None else _revision(row)

    def latest_archived_revision(self, document_id: str) -> DocumentRevisionRecord | None:
        row = self._session.scalar(
            select(DocumentRevision)
            .where(
                DocumentRevision.canonical_document_id == document_id,
                DocumentRevision.object_key.is_not(None),
                DocumentRevision.tombstoned_at.is_(None),
            )
            .order_by(DocumentRevision.created_at.desc(), DocumentRevision.revision_id.desc())
            .limit(1)
        )
        return None if row is None else _revision(row)

    def document_id_by_source_url(self, source_url: str) -> str | None:
        value = self._session.scalar(
            select(DocumentRevision.canonical_document_id).where(
                DocumentRevision.source_url == source_url
            )
        )
        return str(value) if value else None

    def update_revision(self, record: DocumentRevisionRecord) -> None:
        row = self._session.get(DocumentRevision, record.revision_id)
        if row is None:
            raise LookupError(record.revision_id)
        for key, value in record.__dict__.items():
            if key != "created_at":
                setattr(row, key, value)
        self._session.flush()

    def add_run(self, record: IngestionRunRecord) -> None:
        self._session.add(IngestionRun(**record.__dict__))
        self._session.flush()

    def get_run(self, run_id: str) -> IngestionRunRecord | None:
        row = self._session.get(IngestionRun, run_id)
        return None if row is None else _run(row)

    def update_run(self, record: IngestionRunRecord) -> None:
        row = self._session.get(IngestionRun, record.run_id)
        if row is None:
            raise LookupError(record.run_id)
        for key, value in record.__dict__.items():
            if key != "created_at":
                setattr(row, key, value)
        self._session.flush()

    def latest_run(self, revision_id: str) -> IngestionRunRecord | None:
        row = self._session.scalar(
            select(IngestionRun)
            .where(IngestionRun.revision_id == revision_id)
            .order_by(IngestionRun.created_at.desc())
            .limit(1)
        )
        return None if row is None else _run(row)

    def add_artifacts(self, records: list[IngestionArtifactRecord]) -> None:
        if not records:
            return
        for offset in range(0, len(records), _BULK_WRITE_BATCH_SIZE):
            batch = records[offset : offset + _BULK_WRITE_BATCH_SIZE]
            statement = insert(IngestionArtifact).values([record.__dict__ for record in batch])
            statement = statement.on_conflict_do_update(
                index_elements=["run_id", "artifact_type", "artifact_key"],
                set_={
                    "payload": statement.excluded.payload,
                    "content_hash": statement.excluded.content_hash,
                },
            )
            self._session.execute(statement)
        self._session.flush()

    def index_artifacts(
        self,
        *,
        run_id: str,
        document_id: str,
        visibility_label: str,
        records: list[IngestionArtifactRecord],
    ) -> None:
        segments = [record for record in records if record.artifact_type == "segment"]
        if not segments:
            return
        segment_ids: dict[str, int] = {}
        for offset in range(0, len(segments), _BULK_WRITE_BATCH_SIZE):
            locator_batch = [
                record.artifact_key for record in segments[offset : offset + _BULK_WRITE_BATCH_SIZE]
            ]
            segment_ids.update(
                {
                    str(locator): int(segment_id)
                    for locator, segment_id in self._session.execute(
                        select(DocumentSegment.locator, DocumentSegment.id).where(
                            DocumentSegment.document_id == document_id,
                            DocumentSegment.locator.in_(locator_batch),
                        )
                    )
                }
            )
        values = [
            {
                "index_id": f"{run_id}:{record.artifact_key}",
                "segment_id": segment_ids.get(record.artifact_key),
                "ingestion_run_id": run_id,
                "document_id": document_id,
                "locator": record.artifact_key,
                "content": str(record.payload.get("content", "")),
                "visibility_label": visibility_label,
            }
            for record in segments
        ]
        for offset in range(0, len(values), _BULK_WRITE_BATCH_SIZE):
            statement = insert(SegmentSearchIndex).values(
                values[offset : offset + _BULK_WRITE_BATCH_SIZE]
            )
            statement = statement.on_conflict_do_update(
                index_elements=["index_id"],
                set_={
                    "segment_id": statement.excluded.segment_id,
                    "document_id": statement.excluded.document_id,
                    "locator": statement.excluded.locator,
                    "content": statement.excluded.content,
                    "visibility_label": statement.excluded.visibility_label,
                },
            )
            self._session.execute(statement)
        self._session.flush()
        self._session.execute(
            text(
                "UPDATE segment_search_index SET search_vector="
                "to_tsvector('simple',coalesce(content,'')) WHERE ingestion_run_id=:run_id"
            ),
            {"run_id": run_id},
        )

    def inventory(self) -> dict[str, int]:
        def count(model) -> int:
            return int(self._session.scalar(select(func.count()).select_from(model)) or 0)

        single_segment = self._session.scalar(
            select(func.count()).select_from(
                select(DocumentSegment.document_id)
                .group_by(DocumentSegment.document_id)
                .having(func.count() == 1)
                .subquery()
            )
        )
        archived_document = exists().where(
            DocumentRevision.canonical_document_id == Document.document_id,
            DocumentRevision.object_key.is_not(None),
            DocumentRevision.tombstoned_at.is_(None),
        )
        verified_document = exists().where(
            DocumentRevision.canonical_document_id == Document.document_id,
            DocumentRevision.authorization_status.in_(
                ("公开披露已核验", "用户授权上传", "项目自有")
            ),
            DocumentRevision.tombstoned_at.is_(None),
        )
        active_document = Document.deleted_at.is_(None)
        return {
            "documents": count(Document),
            "revisions": count(DocumentRevision),
            "ingestion_runs": count(IngestionRun),
            "segments": count(DocumentSegment),
            "facts": count(DocumentFact),
            "single_segment_documents": int(single_segment or 0),
            "semantic_runs": int(
                self._session.scalar(
                    select(func.count())
                    .select_from(IngestionRun)
                    .where(IngestionRun.chunker_version == "semantic-v1")
                )
                or 0
            ),
            "artifact_segments": int(
                self._session.scalar(
                    select(func.count())
                    .select_from(IngestionArtifact)
                    .where(IngestionArtifact.artifact_type == "segment")
                )
                or 0
            ),
            "artifact_facts": int(
                self._session.scalar(
                    select(func.count())
                    .select_from(IngestionArtifact)
                    .where(IngestionArtifact.artifact_type == "fact")
                )
                or 0
            ),
            "artifact_events": int(
                self._session.scalar(
                    select(func.count())
                    .select_from(IngestionArtifact)
                    .where(IngestionArtifact.artifact_type == "event")
                )
                or 0
            ),
            "pending_authorization": int(
                self._session.scalar(
                    select(func.count())
                    .select_from(Document)
                    .where(active_document, ~verified_document)
                )
                or 0
            ),
            "missing_object_archive": int(
                self._session.scalar(
                    select(func.count())
                    .select_from(Document)
                    .where(active_document, ~archived_document)
                )
                or 0
            ),
            "embeddings": count(SegmentEmbedding),
            "title_index_documents": int(
                self._session.scalar(
                    select(func.count())
                    .select_from(Document)
                    .where(active_document, Document.content_status == "标题索引")
                )
                or 0
            ),
            "archived_source_documents": int(
                self._session.scalar(
                    select(func.count())
                    .select_from(Document)
                    .where(active_document, archived_document)
                )
                or 0
            ),
            "authorization_verified_documents": int(
                self._session.scalar(
                    select(func.count())
                    .select_from(Document)
                    .where(active_document, verified_document)
                )
                or 0
            ),
        }

    def catalog_overview(self, *, visibility_labels: tuple[str, ...]) -> dict[str, int]:
        if not visibility_labels:
            return {
                "documents": 0,
                "archived_documents": 0,
                "missing_archive_documents": 0,
                "authorization_verified_documents": 0,
                "pending_authorization_documents": 0,
                "title_index_documents": 0,
                "full_text_documents": 0,
                "recent_succeeded_runs": 0,
                "recent_failed_runs": 0,
            }
        counts = (
            self._session.execute(
                text(
                    """SELECT count(*)::int AS documents,
                          count(*) FILTER (WHERE EXISTS (
                            SELECT 1 FROM document_revision rev
                            WHERE COALESCE(rev.canonical_document_id,rev.document_id)=d.document_id
                              AND rev.object_key IS NOT NULL AND rev.tombstoned_at IS NULL
                          ))::int AS archived_documents,
                          count(*) FILTER (WHERE NOT EXISTS (
                            SELECT 1 FROM document_revision rev
                            WHERE COALESCE(rev.canonical_document_id,rev.document_id)=d.document_id
                              AND rev.object_key IS NOT NULL AND rev.tombstoned_at IS NULL
                          ))::int AS missing_archive_documents,
                          count(*) FILTER (WHERE EXISTS (
                            SELECT 1 FROM document_revision rev
                            WHERE COALESCE(rev.canonical_document_id,rev.document_id)=d.document_id
                              AND rev.authorization_status=ANY(CAST(:verified AS text[]))
                              AND rev.tombstoned_at IS NULL
                          ))::int AS authorization_verified_documents,
                          count(*) FILTER (WHERE NOT EXISTS (
                            SELECT 1 FROM document_revision rev
                            WHERE COALESCE(rev.canonical_document_id,rev.document_id)=d.document_id
                              AND rev.authorization_status=ANY(CAST(:verified AS text[]))
                              AND rev.tombstoned_at IS NULL
                          ))::int AS pending_authorization_documents,
                          count(*) FILTER (WHERE d.content_status='标题索引')::int
                            AS title_index_documents,
                          count(*) FILTER (WHERE d.content_status='完整正文')::int
                            AS full_text_documents
                   FROM document d
                   WHERE d.deleted_at IS NULL
                     AND d.visibility_label=ANY(CAST(:labels AS text[]))"""
                ),
                {
                    "labels": list(visibility_labels),
                    "verified": ["公开披露已核验", "用户授权上传", "项目自有"],
                },
            )
            .mappings()
            .one()
        )
        runs = (
            self._session.execute(
                text(
                    """SELECT count(*) FILTER (WHERE ir.status='succeeded')::int
                            AS recent_succeeded_runs,
                          count(*) FILTER (WHERE ir.status IN ('failed','dead_letter'))::int
                            AS recent_failed_runs
                   FROM ingestion_run ir
                   JOIN document_revision rev ON rev.revision_id=ir.revision_id
                   JOIN document d
                     ON d.document_id=COALESCE(rev.canonical_document_id,rev.document_id)
                   WHERE d.deleted_at IS NULL
                     AND d.visibility_label=ANY(CAST(:labels AS text[]))
                     AND ir.created_at >= now()-interval '7 days'"""
                ),
                {"labels": list(visibility_labels)},
            )
            .mappings()
            .one()
        )
        return {key: int(value or 0) for key, value in {**dict(counts), **dict(runs)}.items()}

    def list_documents(
        self,
        *,
        visibility_labels: tuple[str, ...],
        query: str | None,
        content_status: str | None,
        source_id: str | None,
        doc_type: str | None,
        security_id: str | None,
        industry: str | None,
        authorization_status: str | None,
        archived: bool | None,
        run_status: str | None,
        visibility_label: str | None,
        published_from,
        published_to,
        include_deleted: bool,
        sort: str,
        direction: str,
        limit: int,
        offset: int,
    ) -> tuple[list[AssetDocumentRecord], int]:
        if not visibility_labels:
            return [], 0
        escaped = (
            (query or "").strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        filters = """
WHERE (CAST(:query AS text) IS NULL OR document_id ILIKE :pattern ESCAPE '\\'
       OR title ILIKE :pattern ESCAPE '\\' OR source_name ILIKE :pattern ESCAPE '\\'
       OR COALESCE(search_body,'') ILIKE :pattern ESCAPE '\\')
  AND (CAST(:content_status AS text) IS NULL OR content_status=:content_status)
  AND (CAST(:source_id AS text) IS NULL OR source_id=:source_id)
  AND (CAST(:doc_type AS text) IS NULL OR doc_type=:doc_type)
  AND (CAST(:security_id AS text) IS NULL OR :security_id=ANY(security_ids))
  AND (CAST(:industry AS text) IS NULL OR :industry=ANY(industries))
  AND (CAST(:authorization_status AS text) IS NULL
       OR authorization_status=:authorization_status)
  AND (CAST(:archived AS boolean) IS NULL OR archived=:archived)
  AND (CAST(:run_status AS text) IS NULL OR latest_run_status=:run_status)
  AND (CAST(:visibility_label AS text) IS NULL OR visibility_label=:visibility_label)
  AND (CAST(:published_from AS timestamptz) IS NULL
       OR published_at>=CAST(:published_from AS timestamptz))
  AND (CAST(:published_to AS timestamptz) IS NULL
       OR published_at<=CAST(:published_to AS timestamptz))
"""
        normalized_query = (query or "").strip() or None
        params = {
            "labels": list(visibility_labels),
            "include_deleted": include_deleted,
            "query": normalized_query,
            "pattern": f"%{escaped}%",
            "content_status": content_status,
            "source_id": source_id,
            "doc_type": doc_type,
            "security_id": security_id,
            "industry": industry,
            "authorization_status": authorization_status,
            "archived": archived,
            "run_status": run_status,
            "visibility_label": visibility_label,
            "published_from": published_from,
            "published_to": published_to,
            "limit": max(1, min(limit, 100)),
            "offset": max(0, offset),
        }
        total = int(
            self._session.scalar(
                text(_DOCUMENT_CATALOG_CTE + "SELECT count(*) FROM catalog " + filters), params
            )
            or 0
        )
        order_columns = {
            "published_at": "published_at",
            "ingested_at": "ingested_at",
            "title": "title",
            "content_status": "content_status",
            "latest_run_at": "latest_run_at",
        }
        order_column = order_columns.get(sort, "published_at")
        order_direction = "ASC" if direction.lower() == "asc" else "DESC"
        statement = (
            _DOCUMENT_CATALOG_CTE
            + "SELECT * FROM catalog "
            + filters
            + f" ORDER BY {order_column} {order_direction} NULLS LAST,document_id ASC"
            + " LIMIT :limit OFFSET :offset"
        )
        rows = self._session.execute(text(statement), params).mappings()
        return [_catalog_record(row) for row in rows], total

    def get_document_catalog(
        self,
        document_id: str,
        *,
        visibility_labels: tuple[str, ...],
        include_deleted: bool = False,
    ) -> AssetDocumentRecord | None:
        if not visibility_labels:
            return None
        row = (
            self._session.execute(
                text(
                    _DOCUMENT_CATALOG_CTE + "SELECT * FROM catalog WHERE document_id=:document_id"
                ),
                {
                    "labels": list(visibility_labels),
                    "include_deleted": include_deleted,
                    "document_id": document_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _catalog_record(row)

    def list_document_revisions(self, document_id: str) -> list[DocumentRevisionRecord]:
        rows = self._session.scalars(
            select(DocumentRevision)
            .where(
                func.coalesce(DocumentRevision.canonical_document_id, DocumentRevision.document_id)
                == document_id
            )
            .order_by(DocumentRevision.created_at.desc(), DocumentRevision.revision_id.desc())
        ).all()
        return [_revision(row) for row in rows]

    def list_document_runs(self, document_id: str) -> list[AssetRunCatalogRecord]:
        rows = self._session.execute(
            text(
                """SELECT ir.*,COALESCE(rev.canonical_document_id,rev.document_id) AS document_id,
                          COALESCE(NULLIF(BTRIM(d.title),''),d.document_id) AS document_title,
                          rev.source_filename
                   FROM ingestion_run ir
                   JOIN document_revision rev ON rev.revision_id=ir.revision_id
                   JOIN document d
                     ON d.document_id=COALESCE(rev.canonical_document_id,rev.document_id)
                   WHERE d.document_id=:document_id
                   ORDER BY ir.created_at DESC,ir.run_id DESC"""
            ),
            {"document_id": document_id},
        ).mappings()
        return [_run_catalog_record(row) for row in rows]

    def list_ingestion_runs(
        self,
        *,
        visibility_labels: tuple[str, ...],
        status: str | None,
        document_id: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AssetRunCatalogRecord], int]:
        if not visibility_labels:
            return [], 0
        base = """ FROM ingestion_run ir
                   JOIN document_revision rev ON rev.revision_id=ir.revision_id
                   JOIN document d
                     ON d.document_id=COALESCE(rev.canonical_document_id,rev.document_id)
                   WHERE d.deleted_at IS NULL
                     AND d.visibility_label=ANY(CAST(:labels AS text[]))
                     AND (CAST(:status AS text) IS NULL OR ir.status=:status)
                     AND (CAST(:document_id AS text) IS NULL OR d.document_id=:document_id)"""
        params = {
            "labels": list(visibility_labels),
            "status": status,
            "document_id": document_id,
            "limit": max(1, min(limit, 100)),
            "offset": max(0, offset),
        }
        total = int(self._session.scalar(text("SELECT count(*)" + base), params) or 0)
        rows = self._session.execute(
            text(
                """SELECT ir.*,COALESCE(rev.canonical_document_id,rev.document_id) AS document_id,
                          COALESCE(NULLIF(BTRIM(d.title),''),d.document_id) AS document_title,
                          rev.source_filename"""
                + base
                + " ORDER BY ir.created_at DESC,ir.run_id DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        ).mappings()
        return [_run_catalog_record(row) for row in rows], total

    def list_sources(self, *, visibility_labels: tuple[str, ...]) -> list[AssetSourceCatalogRecord]:
        if not visibility_labels:
            return []
        rows = self._session.execute(
            text(
                """SELECT src.source_id,src.name,src.source_type,src.authorization_status,
                          src.base_url,src.license_note,src.authorization_basis,
                          src.authorization_verified_by,src.authorization_verified_at,src.active,
                          count(DISTINCT d.document_id)::int AS document_count,
                          (SELECT ir.status FROM ingestion_run ir
                           JOIN document_revision rev ON rev.revision_id=ir.revision_id
                           JOIN document rd
                             ON rd.document_id=COALESCE(rev.canonical_document_id,rev.document_id)
                           WHERE rd.source_id=src.source_id AND rd.deleted_at IS NULL
                             AND rd.visibility_label=ANY(CAST(:labels AS text[]))
                           ORDER BY ir.created_at DESC,ir.run_id DESC LIMIT 1)
                            AS latest_run_status,
                          (SELECT COALESCE(ir.finished_at,ir.started_at,ir.created_at)
                           FROM ingestion_run ir
                           JOIN document_revision rev ON rev.revision_id=ir.revision_id
                           JOIN document rd
                             ON rd.document_id=COALESCE(rev.canonical_document_id,rev.document_id)
                           WHERE rd.source_id=src.source_id AND rd.deleted_at IS NULL
                             AND rd.visibility_label=ANY(CAST(:labels AS text[]))
                           ORDER BY ir.created_at DESC,ir.run_id DESC LIMIT 1)
                            AS latest_run_at
                   FROM source src
                   JOIN document d ON d.source_id=src.source_id AND d.deleted_at IS NULL
                   WHERE d.visibility_label=ANY(CAST(:labels AS text[]))
                   GROUP BY src.source_id
                   ORDER BY document_count DESC,src.name"""
            ),
            {"labels": list(visibility_labels)},
        ).mappings()
        return [
            AssetSourceCatalogRecord(
                source_id=str(row["source_id"]),
                name=str(row["name"]),
                source_type=str(row["source_type"]),
                authorization_status=str(row["authorization_status"]),
                license_note=str(row["license_note"]) if row["license_note"] else None,
                authorization_basis=(
                    str(row["authorization_basis"]) if row["authorization_basis"] else None
                ),
                authorization_verified_by=(
                    str(row["authorization_verified_by"])
                    if row["authorization_verified_by"]
                    else None
                ),
                authorization_verified_at=row["authorization_verified_at"],
                active=bool(row["active"]),
                document_count=int(row["document_count"] or 0),
                latest_run_status=(
                    str(row["latest_run_status"]) if row["latest_run_status"] else None
                ),
                latest_run_at=row["latest_run_at"],
                base_host=urlparse(str(row["base_url"])).hostname if row["base_url"] else None,
            )
            for row in rows
        ]

    def add_thesis_revision(self, record: ThesisRevisionDraftRecord) -> None:
        self._session.add(ThesisRevisionDraft(**record.__dict__))
        self._session.flush()

    def get_thesis_revision(self, draft_id: str) -> ThesisRevisionDraftRecord | None:
        row = self._session.get(ThesisRevisionDraft, draft_id)
        return None if row is None else _draft(row)

    def active_thesis_revision(self, thesis_id: str) -> ThesisRevisionDraftRecord | None:
        row = self._session.scalar(
            select(ThesisRevisionDraft).where(
                ThesisRevisionDraft.thesis_id == thesis_id,
                ThesisRevisionDraft.status == "editing",
            )
        )
        return None if row is None else _draft(row)

    def update_thesis_revision(self, record: ThesisRevisionDraftRecord) -> None:
        row = self._session.get(ThesisRevisionDraft, record.draft_id)
        if row is None:
            raise LookupError(record.draft_id)
        row.revision = record.revision
        row.payload = record.payload
        row.status = record.status
        self._session.flush()

    def rebuild_search_index(self) -> int:
        # TRUNCATE avoids retaining hundreds of thousands of deleted row versions and the
        # corresponding WAL volume.  Reinsert in bounded document batches so PostgreSQL does
        # not have to build every tsvector in one executor invocation.
        self._session.execute(text("TRUNCATE TABLE segment_search_index CASCADE"))
        document_ids = list(
            self._session.scalars(
                select(Document.document_id)
                .where(Document.deleted_at.is_(None))
                .order_by(Document.document_id)
            )
        )
        for offset in range(0, len(document_ids), _SEARCH_REBUILD_DOCUMENT_BATCH_SIZE):
            document_batch = document_ids[offset : offset + _SEARCH_REBUILD_DOCUMENT_BATCH_SIZE]
            self._session.execute(
                text(
                    """WITH latest_run AS (
                     SELECT DISTINCT ON (ir.revision_id)
                            ir.run_id, r.canonical_document_id AS document_id
                     FROM ingestion_run ir
                     JOIN document_revision r ON r.revision_id=ir.revision_id
                     WHERE ir.status='succeeded' AND r.canonical_document_id IS NOT NULL
                           AND r.tombstoned_at IS NULL
                     ORDER BY ir.revision_id, ir.created_at DESC, ir.run_id DESC
                   )
                   INSERT INTO segment_search_index
                   (index_id,segment_id,ingestion_run_id,document_id,locator,content,visibility_label,
                    search_vector)
                   SELECT 'active:' || a.run_id || ':' || a.artifact_key,s.id,a.run_id,
                          lr.document_id,a.artifact_key,a.payload->>'content',d.visibility_label,
                          to_tsvector('simple',coalesce(a.payload->>'content',''))
                   FROM latest_run lr
                   JOIN ingestion_artifact a ON a.run_id=lr.run_id
                                             AND a.artifact_type='segment'
                   JOIN document d ON d.document_id=lr.document_id
                   JOIN document_segment s ON s.document_id=lr.document_id
                                          AND s.locator=a.artifact_key
                   WHERE d.deleted_at IS NULL
                     AND d.document_id = ANY(CAST(:document_ids AS text[]))"""
                ),
                {"document_ids": document_batch},
            )
            self._session.execute(
                text(
                    """INSERT INTO segment_search_index
                   (index_id,segment_id,document_id,locator,content,visibility_label,search_vector)
                   SELECT 'legacy:' || s.id,s.id,s.document_id,s.locator,s.content,
                          d.visibility_label,to_tsvector('simple',coalesce(s.content,''))
                   FROM document_segment s JOIN document d ON d.document_id=s.document_id
                   WHERE d.deleted_at IS NULL
                     AND d.document_id = ANY(CAST(:document_ids AS text[]))
                     AND NOT EXISTS (
                     SELECT 1 FROM segment_search_index i
                     WHERE i.document_id=d.document_id AND i.locator=s.locator
                   )"""
                ),
                {"document_ids": document_batch},
            )
        count = self._session.scalar(select(func.count()).select_from(SegmentSearchIndex))
        return int(count or 0)

    def sync_document_visibility(self, document_id: str, visibility_label: str) -> None:
        self._session.execute(
            update(SegmentSearchIndex)
            .where(SegmentSearchIndex.document_id == document_id)
            .values(visibility_label=visibility_label)
        )
        self._session.flush()

    def remove_document_from_index(self, document_id: str) -> None:
        self._session.execute(
            delete(SegmentSearchIndex).where(SegmentSearchIndex.document_id == document_id)
        )
        self._session.flush()

    def tombstone_revisions(self, document_id: str, tombstoned_at) -> None:
        self._session.execute(
            update(DocumentRevision)
            .where(
                func.coalesce(DocumentRevision.canonical_document_id, DocumentRevision.document_id)
                == document_id
            )
            .values(tombstoned_at=tombstoned_at)
        )
        self._session.flush()

    def restore_revisions(self, document_id: str) -> None:
        self._session.execute(
            update(DocumentRevision)
            .where(
                func.coalesce(DocumentRevision.canonical_document_id, DocumentRevision.document_id)
                == document_id
            )
            .values(tombstoned_at=None)
        )
        self._session.flush()

    def search_segments(
        self, *, query: str, visibility_labels: tuple[str, ...], limit: int
    ) -> list[AssetSearchHitRecord]:
        if not query.strip() or not visibility_labels:
            return []
        escaped = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = self._session.execute(
            text(
                """SELECT i.document_id, i.locator, i.content, i.visibility_label,
                          d.published_at,d.content_status,
                          COALESCE(s.content_kind,'paragraph') AS content_kind,
                          COALESCE(NULLIF(BTRIM(d.title),''),
                                   NULLIF(BTRIM(d.source_id),''),d.document_id)
                            AS source,
                          ts_rank_cd(i.search_vector, plainto_tsquery('simple', :query)) AS rank
                   FROM segment_search_index i
                   JOIN document d ON d.document_id=i.document_id AND d.deleted_at IS NULL
                   LEFT JOIN document_segment s ON s.id=i.segment_id
                   WHERE i.visibility_label = ANY(:labels)
                     AND (i.search_vector @@ plainto_tsquery('simple', :query)
                          OR i.content ILIKE :pattern ESCAPE '\\')
                   ORDER BY rank DESC, i.document_id, i.locator
                   LIMIT :limit"""
            ),
            {
                "query": query.strip(),
                "pattern": f"%{escaped}%",
                "labels": list(visibility_labels),
                "limit": limit,
            },
        ).mappings()
        return [
            AssetSearchHitRecord(
                document_id=str(row["document_id"]),
                locator=str(row["locator"]),
                content=str(row["content"]),
                visibility_label=str(row["visibility_label"]),
                rank=float(row["rank"] or 0),
                published_at=row["published_at"],
                source=str(row["source"]),
                content_status=str(row["content_status"]),
                content_kind=str(row["content_kind"]),
            )
            for row in rows
        ]

    def pending_embedding_sources(
        self, *, embedding_version: str, limit: int
    ) -> list[EmbeddingSourceRecord]:
        rows = self._session.execute(
            select(
                SegmentSearchIndex.index_id,
                SegmentSearchIndex.ingestion_run_id,
                SegmentSearchIndex.document_id,
                SegmentSearchIndex.locator,
                SegmentSearchIndex.content,
            )
            .outerjoin(
                SegmentEmbedding,
                (SegmentEmbedding.index_id == SegmentSearchIndex.index_id)
                & (SegmentEmbedding.embedding_version == embedding_version),
            )
            .where(SegmentEmbedding.id.is_(None))
            .order_by(SegmentSearchIndex.index_id)
            .limit(limit)
        ).all()
        return [EmbeddingSourceRecord(*row) for row in rows]

    def upsert_embeddings(self, records: list[SegmentEmbeddingRecord]) -> int:
        if not records:
            return 0
        statement = text(
            """INSERT INTO segment_embedding
               (index_id,ingestion_run_id,document_id,locator,embedding_version,embedding)
               VALUES (:index_id,:ingestion_run_id,:document_id,:locator,:embedding_version,
                       CAST(:embedding AS vector))
               ON CONFLICT (index_id,embedding_version) DO NOTHING"""
        )
        self._session.execute(
            statement,
            [
                {
                    "index_id": record.index_id,
                    "ingestion_run_id": record.ingestion_run_id,
                    "document_id": record.document_id,
                    "locator": record.locator,
                    "embedding_version": record.embedding_version,
                    "embedding": "[" + ",".join(f"{value:.9g}" for value in record.embedding) + "]",
                }
                for record in records
            ],
        )
        # The input batch is already limited to rows missing this version.  The
        # unique constraint remains the final race-safe guard for concurrent builders.
        return len(records)

    def hybrid_search_segments(
        self,
        *,
        query: str,
        query_embedding: list[float],
        embedding_version: str,
        visibility_labels: tuple[str, ...],
        security_ids: tuple[str, ...],
        industries: tuple[str, ...],
        published_from,
        published_to,
        keyword_weight: float,
        vector_weight: float,
        limit: int,
    ) -> list[AssetSearchHitRecord]:
        if not query.strip() or not visibility_labels:
            return []
        normalized_query = "".join(query.lower().split())
        literal_terms = sorted(
            {
                normalized_query[index : index + 2]
                for index in range(max(0, len(normalized_query) - 1))
                if any("\u4e00" <= char <= "\u9fff" for char in normalized_query[index : index + 2])
            }
        )
        vector = "[" + ",".join(f"{value:.9g}" for value in query_embedding) + "]"
        rows = self._session.execute(
            text(
                """WITH filtered AS (
                     SELECT i.index_id,i.ingestion_run_id,i.document_id,i.locator,i.content,
                            i.visibility_label,i.search_vector,e.embedding,d.published_at,
                            d.content_status,
                            COALESCE(s.content_kind,'paragraph') AS content_kind,
                            COALESCE(NULLIF(BTRIM(d.title),''),
                                     NULLIF(BTRIM(d.source_id),''),d.document_id)
                              AS source
                     FROM segment_search_index i
                     JOIN segment_embedding e ON e.index_id=i.index_id
                                              AND e.embedding_version=:embedding_version
                     JOIN document d ON d.document_id=i.document_id AND d.deleted_at IS NULL
                     LEFT JOIN document_segment s ON s.id=i.segment_id
                     WHERE i.visibility_label = ANY(:labels)
                       AND (CAST(:published_from AS timestamptz) IS NULL
                            OR d.published_at >= CAST(:published_from AS timestamptz))
                       AND (CAST(:published_to AS timestamptz) IS NULL
                            OR d.published_at <= CAST(:published_to AS timestamptz))
                       AND (cardinality(CAST(:security_ids AS text[]))=0 OR EXISTS (
                         SELECT 1 FROM document_security_relation dsr
                         WHERE dsr.document_id=i.document_id
                           AND dsr.security_id = ANY(CAST(:security_ids AS text[]))
                           AND dsr.status='已确认'))
                       AND (cardinality(CAST(:industries AS text[]))=0 OR EXISTS (
                         SELECT 1 FROM document_security_relation dsr
                         JOIN security_industry_membership sim ON sim.security_id=dsr.security_id
                         JOIN industry ind ON ind.industry_id=sim.industry_id
                         WHERE dsr.document_id=i.document_id AND dsr.status='已确认'
                           AND ind.name = ANY(CAST(:industries AS text[]))
                           AND sim.valid_from <= d.published_at::date
                           AND (sim.valid_to IS NULL OR sim.valid_to >= d.published_at::date)))
                   ), raw_scored AS (
                     SELECT *,
                       ts_rank_cd(search_vector,plainto_tsquery('simple',:query)) AS ts_rank,
                       CASE WHEN cardinality(CAST(:literal_terms AS text[]))=0 THEN 0
                            ELSE (SELECT count(*)::float
                                  FROM unnest(CAST(:literal_terms AS text[])) AS term
                                  WHERE content ILIKE ('%' || term || '%'))
                                 / cardinality(CAST(:literal_terms AS text[])) END AS literal_rank,
                       1-(embedding <=> CAST(:embedding AS vector)) AS vector_rank
                     FROM filtered
                   ), scored AS (
                     SELECT *, GREATEST(ts_rank, literal_rank) AS keyword_rank
                     FROM raw_scored
                   )
                   SELECT document_id,locator,content,visibility_label,published_at,source,
                          content_status,content_kind,
                          ingestion_run_id,
                          keyword_rank,vector_rank,
                          (:keyword_weight*keyword_rank)+(:vector_weight*GREATEST(vector_rank,0)) AS rank
                   FROM scored
                   ORDER BY rank DESC,document_id,locator LIMIT :limit"""
            ),
            {
                "query": query.strip(),
                "literal_terms": literal_terms,
                "embedding": vector,
                "embedding_version": embedding_version,
                "labels": list(visibility_labels),
                "security_ids": list(security_ids),
                "industries": list(industries),
                "published_from": published_from,
                "published_to": published_to,
                "keyword_weight": keyword_weight,
                "vector_weight": vector_weight,
                "limit": limit,
            },
        ).mappings()
        return [
            AssetSearchHitRecord(
                document_id=str(row["document_id"]),
                locator=str(row["locator"]),
                content=str(row["content"]),
                visibility_label=str(row["visibility_label"]),
                rank=float(row["rank"] or 0),
                published_at=row["published_at"],
                source=str(row["source"]),
                retrieval_mode="hybrid",
                keyword_rank=float(row["keyword_rank"] or 0),
                vector_rank=float(row["vector_rank"] or 0),
                ingestion_run_id=(
                    str(row["ingestion_run_id"]) if row["ingestion_run_id"] else None
                ),
                embedding_version=embedding_version,
                content_status=str(row["content_status"]),
                content_kind=str(row["content_kind"]),
            )
            for row in rows
        ]
