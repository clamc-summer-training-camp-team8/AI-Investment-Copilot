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


class DocumentSegmentOut(BaseModel):
    document_id: str
    title: str | None
    locator: str
    ordinal: int
    page: int | None
    content: str
    previous_locator: str | None = None
    next_locator: str | None = None
