"""Request and response schemas for the review center."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ReviewTaskCreateIn(BaseModel):
    thesis_id: str = Field(min_length=1, max_length=64)
    trigger: Literal["到期", "重大事件", "失效条件", "人工发起", "低置信", "处理失败"] = "人工发起"
    priority: Literal["低", "普通", "高", "紧急"] = "普通"
    assignee: str | None = Field(default=None, max_length=64)
    detail: dict[str, Any] | None = None


class ReviewTaskResolveIn(BaseModel):
    resolution: str = Field(min_length=2, max_length=2000)


class ReviewTaskOut(BaseModel):
    task_id: str
    thesis_id: str
    trigger: str
    priority: str
    assignee: str
    state: str
    detail: dict[str, Any] | None
    resolution: str | None
    created_at: datetime | None
    resolved_at: datetime | None
