"""Asynchronous job response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class JobAcceptedOut(BaseModel):
    job_id: str
    document_id: str
    status: str = "queued"


class JobStatusOut(BaseModel):
    job_id: str
    status: str
    success: bool | None = None
    result: Any = None
    enqueue_time: datetime | None = None
    start_time: datetime | None = None
    finish_time: datetime | None = None


class ProcessingJobOut(BaseModel):
    job_id: str
    document_id: str
    source_filename: str
    security_id: str | None
    status: str
    attempt_count: int
    max_attempts: int
    result: dict[str, Any] | None
    last_error: str | None
    created_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None


class DocumentSegmentOut(BaseModel):
    document_id: str
    title: str | None
    locator: str
    ordinal: int
    page: int | None
    content: str
    content_kind: str = "paragraph"
    extraction_method: str = "native"
    table_index: int | None = None
    row_index: int | None = None
    cell_range: str | None = None
    confidence: float | None = None
    previous_locator: str | None = None
    next_locator: str | None = None


class DocumentFullOut(BaseModel):
    """完整入库文档阅读视图；正文由已解析段落构成，便于精确回查。"""

    document_id: str
    title: str | None
    doc_type: str | None = None
    published_at: datetime
    parser_version: str
    segment_count: int
    segments: list[DocumentSegmentOut]
