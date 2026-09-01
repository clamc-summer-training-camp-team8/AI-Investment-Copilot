from __future__ import annotations

from datetime import datetime

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
    created_at: datetime | None = None


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
