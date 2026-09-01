from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AssetInventoryOut(Base):
    documents: int
    revisions: int
    ingestion_runs: int
    segments: int
    facts: int
    single_segment_documents: int
    pending_authorization: int = 0
    missing_object_archive: int = 0
    semantic_runs: int = 0
    artifact_segments: int = 0
    artifact_facts: int = 0
    artifact_events: int = 0
    embeddings: int = 0
    title_index_documents: int = 0
    archived_source_documents: int = 0
    authorization_verified_documents: int = 0


class IngestionRunOut(Base):
    run_id: str
    revision_id: str
    parser_version: str
    chunker_version: str
    extractor_version: str
    embedding_version: str | None = None
    status: str
    segment_count: int
    fact_count: int
    event_count: int
    quality_summary: dict[str, object]
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None


class AssetRunOut(IngestionRunOut):
    document_id: str
    document_title: str
    source_filename: str


class AssetRunPageOut(Base):
    items: list[AssetRunOut]
    total: int
    limit: int
    offset: int


class AssetAttentionOut(Base):
    code: str
    label: str
    count: int
    severity: str
    target: str


class AssetOverviewOut(Base):
    documents: int
    archived_documents: int
    missing_archive_documents: int
    authorization_verified_documents: int
    pending_authorization_documents: int
    title_index_documents: int
    full_text_documents: int
    recent_succeeded_runs: int
    recent_failed_runs: int
    market_dataset_count: int
    signal_set_count: int
    default_market_dataset_id: str | None = None
    default_market_data_version: str | None = None
    default_market_coverage_end: date | None = None
    attention: list[AssetAttentionOut] = Field(default_factory=list)
    recent_runs: list[AssetRunOut] = Field(default_factory=list)
    as_of: datetime


class AssetDocumentOut(Base):
    document_id: str
    title: str
    source_id: str | None = None
    source_name: str
    doc_type: str | None = None
    published_at: datetime
    ingested_at: datetime | None = None
    content_status: str
    visibility_label: str
    is_illustrative: bool
    deleted_at: datetime | None = None
    archived: bool
    authorization_status: str
    revision_count: int
    segment_count: int
    latest_run_status: str | None = None
    latest_run_at: datetime | None = None
    security_ids: list[str] = Field(default_factory=list)
    security_names: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)


class AssetDocumentPageOut(Base):
    items: list[AssetDocumentOut]
    total: int
    limit: int
    offset: int


class AssetRevisionOut(Base):
    revision_id: str
    content_hash: str
    source_filename: str
    has_object: bool
    object_version_id: str | None = None
    media_type: str | None = None
    byte_size: int | None = None
    source_id: str | None = None
    source_host: str | None = None
    authorization_status: str
    authorization_basis: str | None = None
    authorization_verified_by: str | None = None
    authorization_verified_at: datetime | None = None
    content_status: str
    uploaded_by: str
    published_at: datetime | None = None
    created_at: datetime | None = None
    tombstoned_at: datetime | None = None


class AssetDocumentDetailOut(AssetDocumentOut):
    allowed_actions: list[str] = Field(default_factory=list)
    revisions: list[AssetRevisionOut] = Field(default_factory=list)
    runs: list[AssetRunOut] = Field(default_factory=list)


class AssetSourceOut(Base):
    source_id: str
    name: str
    source_type: str
    authorization_status: str
    license_note: str | None = None
    authorization_basis: str | None = None
    authorization_verified_by: str | None = None
    authorization_verified_at: datetime | None = None
    active: bool
    document_count: int
    latest_run_status: str | None = None
    latest_run_at: datetime | None = None
    base_host: str | None = None


class RestoreDocumentIn(Base):
    visibility_label: str = Field(default="内部受限", min_length=1, max_length=32)


class ReprocessIn(Base):
    document_id: str = Field(min_length=1, max_length=64)


class SearchRebuildOut(Base):
    indexed_segments: int


class AssetSearchHitOut(Base):
    document_id: str
    locator: str
    content: str
    visibility_label: str
    rank: float
    retrieval_mode: str = "keyword"
    keyword_rank: float | None = None
    vector_rank: float | None = None
    ingestion_run_id: str | None = None
    embedding_version: str | None = None
    content_status: str = "待核验"
    content_kind: str = "paragraph"
    source: str = ""
    published_at: datetime | None = None


class DocumentVisibilityIn(Base):
    visibility_label: str = Field(min_length=1, max_length=32)


class ThesisRevisionOut(Base):
    draft_id: str
    thesis_id: str
    base_version: int
    revision: int
    owner: str
    payload: dict[str, object]
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ThesisRevisionUpdateIn(Base):
    expected_revision: int = Field(ge=1)
    payload: dict[str, object]


class ThesisRevisionPublishIn(Base):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=2, max_length=2000)


class ThesisRevisionDiffOut(Base):
    draft_id: str
    base_version: int
    changes: dict[str, object]
