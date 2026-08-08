"""请求与响应模型。

两条硬约定（contracts/api/README.md）：

1. **Decimal 用字符串传输**，不用 JSON number。台账里存在
   `-0.019999999999999997` 这类浮点残留，直接透传会出现在研究员屏幕上。
2. **正式 AI 结论必须带来源、引用、模型版本和确认状态**（PRD 12.2），
   因此这些字段在响应模型里是必填而不是可选。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_serializer

TITLE_MAX = 40
CORE_VIEW_MAX = 200


class Base(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)


class HypothesisIn(Base):
    statement: Annotated[str, Field(min_length=1)]
    hypothesis_type: str = "其他"
    importance: str = "辅助"


class ThesisDraftIn(Base):
    """建卡入参。文件上传走单独的接口，这里只接手工观点。"""

    security_id: Annotated[str, Field(min_length=1)]
    view: Annotated[str, Field(min_length=1, max_length=2000)]
    document_id: str | None = None


class ThesisPublishIn(Base):
    """发布入参。这些字段 AI 不许代填（PRD 7.1 第 3 步）。"""

    direction: Annotated[str, Field(pattern="^(看多|看空|观察)$")]
    horizon_end_on: date
    next_review_at: date
    invalidation_require_all: bool = True


class EvidenceActionIn(Base):
    """证据处置入参（FR-R-004 的四个动作）。"""

    action: Annotated[str, Field(pattern="^(确认|驳回|修改关联|暂不判断)$")]
    note: str | None = None
    new_hypothesis_id: str | None = None
    new_direction: str | None = None


class StatusDecisionIn(Base):
    """状态建议处置入参。

    `reason` 是必填且非空：正式状态变更必须填原因（FR-S-003）。这里就拦住，
    不要等到服务层——但服务层也拦一次，因为 API 不是唯一入口。
    """

    suggestion_id: int
    action: Annotated[str, Field(pattern="^(接受|拒绝|修改)$")]
    reason: Annotated[str, Field(min_length=1, max_length=1000)]
    target_status: str | None = None


class HypothesisOut(Base):
    hypothesis_id: str
    statement: str
    hypothesis_type: str
    importance: str
    status: str


class ThesisOut(Base):
    thesis_id: str
    security_id: str
    title: str
    direction: str
    core_view: str
    status: str
    owner: str
    visibility: str
    version: int
    established_on: date
    horizon_end_on: date | None = None
    next_review_at: date | None = None
    hypotheses: list[HypothesisOut] = Field(default_factory=list)


class EvidenceOut(Base):
    evidence_id: str
    thesis_id: str
    hypothesis_id: str
    evidence_type: str
    direction: str
    evidence_locator: str
    confirmation_status: str
    ai_status: str | None = None
    model_version: str | None = None
    prompt_version: str | None = None
    strength: str | None = None
    strength_score: Decimal | None = None
    ai_confidence: Decimal | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None

    @field_serializer("strength_score", "ai_confidence")
    def _decimal_as_str(self, value: Decimal | None) -> str | None:
        return None if value is None else str(value)


class SuggestionOut(Base):
    """状态建议。

    `requires_human_confirmation` 恒为真（除已关闭），界面据此渲染确认入口。
    """

    suggestion_id: int | None = None
    thesis_id: str
    current_status: str
    suggested_status: str
    reasons: list[str]
    triggered_hypotheses: list[str] = Field(default_factory=list)
    rule_version: str
    human_action: str | None = None
    human_reason: str | None = None
    acted_by: str | None = None


class PageMeta(Base):
    """分页元信息。列表接口一律分页（contracts/api/README.md）。"""

    total: int
    limit: int
    offset: int


class ThesisPage(Base):
    items: list[ThesisOut]
    page: PageMeta


class ErrorOut(Base):
    """错误响应。

    `retryable` 让前端区分「重试有用」和「重试没用」：模型不可用属于前者，
    校验失败属于后者（PRD 7.4 要求模型失败时任务排队重试）。
    """

    code: str
    message: str
    retryable: bool = False
    candidates: list[dict[str, str]] | None = None
