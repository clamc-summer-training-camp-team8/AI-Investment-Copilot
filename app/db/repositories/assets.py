"""Repositories for source lineage, immutable revisions and reprocessable artifacts."""

from __future__ import annotations

from sqlalchemy import delete, exists, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.domain import (
    AssetSearchHitRecord,
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
        statement = insert(IngestionArtifact).values([record.__dict__ for record in records])
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
        values = [
            {
                "index_id": f"{run_id}:{record.artifact_key}",
                "ingestion_run_id": run_id,
                "document_id": document_id,
                "locator": record.artifact_key,
                "content": str(record.payload.get("content", "")),
                "visibility_label": visibility_label,
            }
            for record in segments
        ]
        statement = insert(SegmentSearchIndex).values(values)
        statement = statement.on_conflict_do_update(
            index_elements=["index_id"],
            set_={
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
        self._session.execute(delete(SegmentSearchIndex))
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
                   (index_id,ingestion_run_id,document_id,locator,content,visibility_label,
                    search_vector)
                   SELECT 'active:' || a.run_id || ':' || a.artifact_key,a.run_id,
                          lr.document_id,a.artifact_key,a.payload->>'content',d.visibility_label,
                          to_tsvector('simple',coalesce(a.payload->>'content',''))
                   FROM latest_run lr
                   JOIN ingestion_artifact a ON a.run_id=lr.run_id
                                             AND a.artifact_type='segment'
                   JOIN document d ON d.document_id=lr.document_id
                   WHERE d.deleted_at IS NULL"""
            )
        )
        self._session.execute(
            text(
                """INSERT INTO segment_search_index
                   (index_id,segment_id,document_id,locator,content,visibility_label,search_vector)
                   SELECT 'legacy:' || s.id,s.id,s.document_id,s.locator,s.content,
                          d.visibility_label,to_tsvector('simple',coalesce(s.content,''))
                   FROM document_segment s JOIN document d ON d.document_id=s.document_id
                   WHERE d.deleted_at IS NULL AND NOT EXISTS (
                     SELECT 1 FROM segment_search_index i
                     WHERE i.document_id=d.document_id AND i.locator=s.locator
                   )"""
            )
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
            .where(DocumentRevision.canonical_document_id == document_id)
            .values(tombstoned_at=tombstoned_at)
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
                          COALESCE(NULLIF(BTRIM(d.title),''),
                                   NULLIF(BTRIM(d.source_id),''),d.document_id)
                            AS source,
                          ts_rank_cd(i.search_vector, plainto_tsquery('simple', :query)) AS rank
                   FROM segment_search_index i
                   JOIN document d ON d.document_id=i.document_id AND d.deleted_at IS NULL
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
                            COALESCE(NULLIF(BTRIM(d.title),''),
                                     NULLIF(BTRIM(d.source_id),''),d.document_id)
                              AS source
                     FROM segment_search_index i
                     JOIN segment_embedding e ON e.index_id=i.index_id
                                              AND e.embedding_version=:embedding_version
                     JOIN document d ON d.document_id=i.document_id AND d.deleted_at IS NULL
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
                          content_status,
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
            )
            for row in rows
        ]
