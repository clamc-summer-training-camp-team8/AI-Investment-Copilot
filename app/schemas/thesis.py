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
from typing import Annotated, Literal

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
    view: Annotated[str, Field(max_length=2000)] = ""
    document_id: str | None = None
    # 新建逻辑默认使用权限过滤后的历史资料；调用方仍可显式关闭以做无资料对照测试。
    use_rag: bool = True


class ThesisPublishIn(Base):
    """发布入参。这些字段 AI 不许代填（PRD 7.1 第 3 步）。"""

    direction: Annotated[str, Field(pattern="^(看多|看空|观察)$")]
    horizon_end_on: date
    next_review_at: date
    invalidation_require_all: bool = True


class HypothesisUpdateIn(Base):
    statement: Annotated[str, Field(min_length=1, max_length=2000)]
    hypothesis_type: Annotated[str, Field(min_length=1, max_length=32)] = "其他"
    importance: Annotated[str, Field(pattern="^(核心|辅助)$")]
    observation_window: str | None = Field(default=None, max_length=128)
    invalidation_rule: str | None = Field(default=None, max_length=2000)


class MetricMappingIn(Base):
    mapping_id: str | None = Field(default=None, max_length=64)
    metric_id: Annotated[str, Field(min_length=1, max_length=64)]
    metric_version: Annotated[str, Field(min_length=1, max_length=16)] = "v1.0"
    expected_direction: Annotated[str, Field(pattern="^(越高越好|越低越好|不低于阈值|不高于阈值)$")]
    expected_value: Decimal | None = None
    invalidation_threshold: Decimal | None = None
    invalidation_consecutive_periods: int | None = Field(default=None, ge=1, le=12)
    expectation_source: Annotated[str, Field(min_length=1, max_length=255)]


class EvidenceActionIn(Base):
    """证据处置入参（FR-R-004 的四个动作）。"""

    action: Annotated[str, Field(pattern="^(确认|驳回|修改关联|暂不判断)$")]
    note: str | None = None
    new_hypothesis_id: str | None = None
    new_direction: str | None = None


class StatusDecisionIn(Base):
    """状态建议处置入参。

    `reason` 是必填且非空：正式状态变更必须填原因（FR-S-003）。这里就拦住，
    服务层也会再拦一次，因为 API 不是唯一入口。
    """

    suggestion_id: int
    action: Annotated[str, Field(pattern="^(接受|拒绝|修改)$")]
    reason: Annotated[str, Field(min_length=1, max_length=1000)]
    target_status: str | None = None


class MetricMappingOut(Base):
    mapping_id: str
    metric_id: str
    metric_name: str = ""
    expected_value: Decimal | None = None
    invalidation_threshold: Decimal | None = None
    invalidation_consecutive_periods: int | None = None
    metric_version: str
    expected_direction: str
    expectation_source: str
    confirmation_status: str

    @field_serializer("expected_value", "invalidation_threshold")
    def _decimal_as_str(self, value: Decimal | None) -> str | None:
        return None if value is None else str(value)


class HypothesisOut(Base):
    hypothesis_id: str
    statement: str
    hypothesis_type: str
    importance: str
    status: str
    observation_window: str | None = None
    invalidation_rule: str | None = None
    causal_level: str | None = None
    logic_dimension: str | None = None
    quality_warning: str | None = None
    metric_suggestions: list[dict[str, object]] = Field(default_factory=list)
    mappings: list[MetricMappingOut] = Field(default_factory=list)


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
    thesis_kind: str = "canonical"
    thesis_series_id: str | None = None
    hypotheses: list[HypothesisOut] = Field(default_factory=list)
    risk_suggestions: list[dict[str, object]] = Field(default_factory=list)
    invalidation_suggestions: list[dict[str, object]] = Field(default_factory=list)


class PublishReadinessItemOut(Base):
    code: str
    label: str
    passed: bool
    message: str


class PublishReadinessOut(Base):
    ready: bool
    items: list[PublishReadinessItemOut]


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


class EvidenceDetailOut(Base):
    """证据本体详情；关联对象由独立关联接口返回。"""

    evidence_id: str
    security_id: str
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
    fact_excerpt: str
    source_document_id: str
    source_document_title: str
    disclosed_at: datetime
    occurred_at: date | None = None
    ingested_at: datetime
    source_url: str

    @field_serializer("strength_score", "ai_confidence")
    def _decimal_as_str(self, value: Decimal | None) -> str | None:
        return None if value is None else str(value)


class RetrievalScoreComponentsOut(Base):
    text: float = 0.0
    graph: float = 0.0


class GraphPathTraceOut(Base):
    score: float
    node_ids: list[str]
    node_kinds: list[str]
    layers: list[str]
    relations: list[str]
    provenance_locators: list[str]
    explanation: str


class GraphLayerSnapshotOut(Base):
    layer: str
    node_count: int
    content_hash: str


class GraphSnapshotTraceOut(Base):
    snapshot_id: str
    schema_version: str
    builder_version: str
    vocabulary_version: str
    built_at: datetime
    as_of: datetime | None = None
    thesis_ids: list[str]
    security_ids: list[str]
    layers: list[GraphLayerSnapshotOut]


class EvidenceRetrievalTraceOut(Base):
    """证据生成时冻结的双路召回依据；正文仍从原文接口读取。"""

    available: bool
    retrieval_mode: str
    retrieval_version: str
    locator: str
    final_score: float
    score_components: RetrievalScoreComponentsOut
    graph_paths: list[GraphPathTraceOut]
    graph_snapshot: GraphSnapshotTraceOut | None = None


class EvidenceRelationOut(Base):
    """当前单关联模型的只读兼容输出，为多关联表迁移预留 response 形状。"""

    relation_id: str
    thesis_id: str
    hypothesis_id: str
    direction: str
    strength: str | None = None
    status: str
    reason: str | None = None
    created_by: str
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    deactivated_by: str | None = None
    deactivated_at: datetime | None = None
    can_manage: bool


class EvidenceRelationIn(Base):
    thesis_id: Annotated[str, Field(min_length=1)]
    hypothesis_id: Annotated[str, Field(min_length=1)]
    direction: Annotated[str, Field(pattern="^(支持|冲突|中性)$")]
    strength: str | None = None
    reason: Annotated[str, Field(min_length=1, max_length=1000)]


class EvidenceRelationReviewIn(Base):
    action: Annotated[str, Field(pattern="^(确认|驳回|暂不判断)$")]
    reason: str | None = Field(default=None, max_length=1000)


class EvidenceRelationDeactivateIn(Base):
    """解除关系只需记录原因，不混用审核动作字段。"""

    reason: Annotated[str, Field(min_length=1, max_length=1000)]


class EvidenceRelationMutationOut(Base):
    relation: EvidenceRelationOut
    affected_thesis_ids: list[str]


class SuggestionOut(Base):
    """状态建议。

    `requires_human_confirmation` 恒为真（除已关闭），界面据此渲染确认入口。
    """

    suggestion_id: int
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


class ValidationItemOut(Base):
    code: str
    label: str
    status: Annotated[str, Field(pattern="^(passed|warning|failed)$")]
    message: str


class EvidenceFeedItemOut(Base):
    """研究员可直接阅读的证据摘要，内部 ID 只承担跳转与追溯。"""

    evidence_id: str
    relation_id: str
    security_id: str
    security_name: str
    thesis_id: str
    thesis_title: str
    hypothesis_id: str
    hypothesis_statement: str
    source_document_title: str
    fact_excerpt: str
    disclosed_at: datetime
    occurred_at: date | None = None
    source_url: str
    direction: str
    strength: str | None = None
    ai_confidence: Decimal | None = None
    confirmation_status: str
    priority: Annotated[str, Field(pattern="^(high|medium|low)$")]
    can_manage: bool
    validation_items: list[ValidationItemOut]

    @field_serializer("ai_confidence")
    def _confidence_as_str(self, value: Decimal | None) -> str | None:
        return None if value is None else str(value)


class EvidenceFeedPage(Base):
    items: list[EvidenceFeedItemOut]
    page: PageMeta


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


class TrendPointOut(Base):
    """趋势上的一个点。值用字符串传，理由见模块文档第 1 条。"""

    period: str
    value: Decimal
    published_on: date
    acquired_at: datetime | None = None
    source_document_id: str | None = None
    data_version: str | None = None

    @field_serializer("value")
    def _value_as_str(self, value: Decimal) -> str:
        return str(value)


class HypothesisTrendOut(Base):
    """假设趋势。

    口径字段是必填而非可选：FR-V-001 要求同时展示口径、报告期与来源，
    字段可选会让前端拿不到时静默不显示，那条要求就落空了。

    `direction` 取「上升/下降/持平/信息不足」，不是预测。FR-V-002 明确不用
    复杂预测模型，只给方向、斜率与连续性。
    """

    hypothesis_id: str
    statement: str
    metric_id: str
    metric_name: str = ""
    unit: str
    period_type: str
    metric_version: str
    data_version: str | None = None
    direction: str
    slope: Decimal | None = None
    consecutive_decline: int = 0
    consecutive_below_expectation: int = 0
    verdict: str | None = None
    points: list[TrendPointOut] = Field(default_factory=list)
    note: str = ""

    @field_serializer("slope")
    def _slope_as_str(self, value: Decimal | None) -> str | None:
        return None if value is None else str(value)


class AuditOut(Base):
    """一条留痕。"""

    actor: str
    action: str
    object_type: str
    object_id: str
    model_version: str | None = None
    occurred_at: datetime | None = None
    detail: dict[str, object] | None = None


class AuditPage(Base):
    items: list[AuditOut]
    page: PageMeta


class PendingItemOut(Base):
    """一条待办。`kind` 决定前端跳到哪个处置入口。"""

    kind: str
    thesis_id: str
    title: str
    object_id: str
    summary: str
    occurred_on: date | None = None


class WorkbenchOut(Base):
    """工作台聚合。只含当前用户可见的卡片。"""

    status_counts: dict[str, int] = Field(default_factory=dict)
    pending_evidence: list[PendingItemOut] = Field(default_factory=list)
    pending_suggestions: list[PendingItemOut] = Field(default_factory=list)
    review_due: list[PendingItemOut] = Field(default_factory=list)


class AdjudicationOut(Base):
    """一条待裁决样本。

    两位标注者的判断都原样给出，不做合并：裁决界面要让导师看到分歧在哪，
    给一个「系统建议」会引导他跟随而不是判断。
    """

    event_id: str
    company: str
    title: str
    category: str
    annotator_a_hypothesis: str
    annotator_a_direction: str
    annotator_b_hypothesis: str
    annotator_b_direction: str
    disagreement: str
    resolved: bool = False
    decided_hypothesis: str | None = None
    decided_direction: str | None = None
    decision_reason: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None


class AdjudicationDecisionIn(Base):
    hypothesis: str = Field(min_length=1, max_length=255)
    direction: Literal["支持", "冲突", "中性", "无关"]
    reason: str = Field(min_length=2, max_length=2000)


class AdjudicationPage(Base):
    items: list[AdjudicationOut]
    page: PageMeta
