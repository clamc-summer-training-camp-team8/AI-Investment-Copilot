"""后端 Agent 编排接口的请求与响应模型。"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.assets import ThesisRevisionOut


class Base(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)


class MetricRecommendationIn(Base):
    """重新生成指标候选时允许控制数量和事前数据截止日。"""

    top_k: int = Field(default=8, ge=1, le=20)
    as_of: date | None = None


class ReviewDraftIn(Base):
    period_start: date
    period_end: date


class AgentCandidateOut(Base):
    """所有 Agent 候选共用的稳定外层；payload 仍遵循具体 AI Schema。"""

    run_id: str
    task: str
    status: str
    ai_status: str | None = None
    requires_human_review: bool = True
    payload: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class RevisionCandidateOut(Base):
    execution: AgentCandidateOut
    revision: ThesisRevisionOut
