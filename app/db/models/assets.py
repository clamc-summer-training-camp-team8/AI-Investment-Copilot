"""P0-3 research-asset lineage models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, updated_at_column


class Source(Base):
    __tablename__ = "source"

    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    authorization_status: Mapped[str] = mapped_column(String(32), nullable=False, default="待确认")
    base_url: Mapped[str | None] = mapped_column(String(1024))
    license_note: Mapped[str | None] = mapped_column(Text)
    authorization_basis: Mapped[str | None] = mapped_column(Text)
    authorization_verified_by: Mapped[str | None] = mapped_column(String(64))
    authorization_verified_at: Mapped[datetime | None] = mapped_column()
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = created_at_column()


class Industry(Base):
    __tablename__ = "industry"

    industry_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("industry.industry_id"))
    created_at: Mapped[datetime] = created_at_column()


class SecurityIndustryMembership(Base):
    __tablename__ = "security_industry_membership"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    security_id: Mapped[str] = mapped_column(ForeignKey("security.security_id"), nullable=False)
    industry_id: Mapped[str] = mapped_column(ForeignKey("industry.industry_id"), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("source.source_id"))

    __table_args__ = (
        UniqueConstraint("security_id", "industry_id", "valid_from"),
        Index("ix_security_industry_active", "security_id", "valid_to"),
    )


class DocumentSecurityRelation(Base):
    __tablename__ = "document_security_relation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("document.document_id"), nullable=False)
    security_id: Mapped[str] = mapped_column(ForeignKey("security.security_id"), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False, default="主体")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="已确认")
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (UniqueConstraint("document_id", "security_id", "relation_type"),)


class DocumentRevision(Base):
    __tablename__ = "document_revision"

    revision_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    canonical_document_id: Mapped[str | None] = mapped_column(ForeignKey("document.document_id"))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    object_key: Mapped[str | None] = mapped_column(String(1024))
    object_version_id: Mapped[str | None] = mapped_column(String(255))
    media_type: Mapped[str | None] = mapped_column(String(128))
    byte_size: Mapped[int | None] = mapped_column(Integer)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("source.source_id"))
    source_url: Mapped[str | None] = mapped_column(String(2048))
    authorization_status: Mapped[str] = mapped_column(String(32), nullable=False, default="待确认")
    authorization_basis: Mapped[str | None] = mapped_column(Text)
    authorization_verified_by: Mapped[str | None] = mapped_column(String(64))
    authorization_verified_at: Mapped[datetime | None] = mapped_column()
    content_status: Mapped[str] = mapped_column(String(24), nullable=False, default="待核验")
    uploaded_by: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = created_at_column()
    tombstoned_at: Mapped[datetime | None] = mapped_column()

    __table_args__ = (
        UniqueConstraint(
            "canonical_document_id",
            "content_hash",
            name="uq_document_revision_document_content",
        ),
        Index("ix_document_revision_content_hash", "content_hash"),
        Index("ix_document_revision_object_key", "object_key"),
    )


class IngestionRun(Base):
    __tablename__ = "ingestion_run"

    run_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("document_revision.revision_id"), nullable=False
    )
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False)
    chunker_version: Mapped[str] = mapped_column(String(32), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(32), nullable=False)
    embedding_version: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    segment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fact_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quality_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        Index("ix_ingestion_run_revision_status", "revision_id", "status", "created_at"),
    )


class SegmentSearchIndex(Base):
    __tablename__ = "segment_search_index"

    index_id: Mapped[str] = mapped_column(String(192), primary_key=True)
    segment_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_segment.id", ondelete="CASCADE")
    )
    ingestion_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("ingestion_run.run_id", ondelete="CASCADE")
    )
    document_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    locator: Mapped[str] = mapped_column(String(160), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    visibility_label: Mapped[str] = mapped_column(String(32), nullable=False)
    search_vector: Mapped[object | None] = mapped_column(TSVECTOR)
    indexed_at: Mapped[datetime] = created_at_column()


class SegmentEmbedding(Base):
    """Versioned vector derived from one active search projection.

    Embeddings are rebuildable derivatives.  Keeping them in a separate table
    lets a new model coexist with the previous model and prevents an embedding
    rollout from rewriting the immutable ingestion artifacts.
    """

    __tablename__ = "segment_embedding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    index_id: Mapped[str] = mapped_column(
        ForeignKey("segment_search_index.index_id", ondelete="CASCADE"), nullable=False
    )
    ingestion_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("ingestion_run.run_id", ondelete="CASCADE")
    )
    document_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    locator: Mapped[str] = mapped_column(String(160), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(VECTOR(256), nullable=False)
    embedded_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        UniqueConstraint("index_id", "embedding_version"),
        Index("ix_segment_embedding_run_version", "ingestion_run_id", "embedding_version"),
        Index(
            "ix_segment_embedding_hnsw_cosine",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class IngestionArtifact(Base):
    __tablename__ = "ingestion_artifact"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("ingestion_run.run_id", ondelete="CASCADE"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    artifact_key: Mapped[str] = mapped_column(String(160), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (UniqueConstraint("run_id", "artifact_type", "artifact_key"),)


class ThesisRevisionDraft(Base):
    __tablename__ = "thesis_revision_draft"

    draft_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    thesis_id: Mapped[str] = mapped_column(ForeignKey("thesis.thesis_id"), nullable=False)
    base_version: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    owner: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="editing")
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        Index(
            "uq_thesis_revision_editing",
            "thesis_id",
            unique=True,
            postgresql_where=text("status = 'editing'"),
        ),
        Index("ix_thesis_revision_owner", "owner", "status"),
    )
