"""八类核心对象 ORM 模型。

对应数据分析说明书 Table 9：Document / Thesis / Hypothesis / Metric /
Event / Signal / Outcome / Experiment，外加产品侧需要的 Security、
HypothesisMetricMap、Evidence、MetricObservation、ThesisVersion、
StatusSuggestionLog 与 AuditLog。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, created_at_column, updated_at_column


class Security(Base):
    """证券主数据。MVP 只覆盖试点公司清单。"""

    __tablename__ = "security"

    security_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    ticker: Mapped[str | None] = mapped_column(String(32))
    industry: Mapped[str | None] = mapped_column(String(128))
    aliases: Mapped[list | None] = mapped_column(JSONB)
    is_illustrative: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="虚构演示数据标记，禁止用于真实投资结论",
    )
    created_at: Mapped[datetime] = created_at_column()


class Document(Base):
    """原始文档及其解析版本。原文件不可覆盖，改版生成新版本。"""

    __tablename__ = "document"

    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str | None] = mapped_column(String(512))
    source_id: Mapped[str | None] = mapped_column(String(64))
    doc_type: Mapped[str | None] = mapped_column(String(64))
    security_id: Mapped[str | None] = mapped_column(ForeignKey("security.security_id"))

    published_at: Mapped[datetime] = mapped_column(
        nullable=False, comment="首次公开可得时间，收益标签时间起点（FLD-002）"
    )
    ingested_at: Mapped[datetime] = created_at_column()

    content_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="SHA-256，用于去重与版本追踪（FLD-003）"
    )
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    raw_path: Mapped[str | None] = mapped_column(String(1024))
    body: Mapped[str | None] = mapped_column(Text)

    visibility_label: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="内部受限",
        comment="权限标签；证据可见性不得高于来源文档",
    )
    is_illustrative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column()

    __table_args__ = (
        UniqueConstraint("content_hash", "parser_version"),
        Index("ix_document_published_at", "published_at"),
    )


class DocumentSegment(Base):
    """文档切片。保留原生/OCR、段落/表格及单元格级定位元数据。"""

    __tablename__ = "document_segment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("document.document_id", ondelete="CASCADE"), nullable=False
    )
    locator: Mapped[str] = mapped_column(String(128), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="paragraph")
    extraction_method: Mapped[str] = mapped_column(String(16), nullable=False, default="native")
    table_index: Mapped[int | None] = mapped_column(Integer)
    row_index: Mapped[int | None] = mapped_column(Integer)
    cell_range: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))

    __table_args__ = (UniqueConstraint("document_id", "locator"),)


class DocumentFact(Base):
    """正文中的确定性同比事实，供方向判断与后续检索评测使用。"""

    __tablename__ = "document_fact"

    fact_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("document.document_id", ondelete="CASCADE"), nullable=False
    )
    locator: Mapped[str] = mapped_column(String(128), nullable=False)
    fact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    change_rate_low: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    change_rate_high: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    extraction_version: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        Index("ix_document_fact_document", "document_id", "fact_type"),
        UniqueConstraint("document_id", "locator", "fact_type", "metric_name"),
    )


class Thesis(Base):
    """投资逻辑。产品核心业务对象，PRD 4.3 字段字典。"""

    __tablename__ = "thesis"

    thesis_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    security_id: Mapped[str] = mapped_column(ForeignKey("security.security_id"), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    core_view: Mapped[str] = mapped_column(Text, nullable=False)

    established_on: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="逻辑建立日；失效条件的连续期数判定必须按此日期裁剪观察窗口",
    )
    horizon_end_on: Mapped[date | None] = mapped_column(Date)
    next_review_at: Mapped[date | None] = mapped_column(Date)

    owner: Mapped[str] = mapped_column(String(64), nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="团队")
    team: Mapped[str | None] = mapped_column(
        String(64),
        comment="归属团队；visibility=团队 时的可见范围判断依据，缺失则同组也看不到",
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="草稿")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    invalidation_require_all: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment=(
            "thesis 级失效条件是「全部满足」还是「任一满足」。"
            "默认 AND：把 AND 当 OR 会让单指标不达标就判失效，误报比漏报更伤信任"
        ),
    )
    draft_suggestions: Mapped[dict | None] = mapped_column(
        JSONB,
        comment="AI 草稿建议候选；未经研究员采用不得进入正式配置",
    )

    source_document_id: Mapped[str | None] = mapped_column(ForeignKey("document.document_id"))
    is_illustrative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    hypotheses: Mapped[list[Hypothesis]] = relationship(
        back_populates="thesis", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("char_length(title) <= 120", name="title_len"),
        CheckConstraint("version >= 0", name="version_nonneg"),
        Index("ix_thesis_status", "status"),
        Index("ix_thesis_owner", "owner"),
    )


class Hypothesis(Base):
    """关键假设。必须可观察、可证伪，并明确观察窗口和失效条件。"""

    __tablename__ = "hypothesis"

    hypothesis_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thesis_id: Mapped[str] = mapped_column(
        ForeignKey("thesis.thesis_id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("hypothesis.hypothesis_id"))

    name: Mapped[str | None] = mapped_column(String(255))
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    hypothesis_type: Mapped[str] = mapped_column(String(32), nullable=False)
    importance: Mapped[str] = mapped_column(String(16), nullable=False)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    observation_window: Mapped[str | None] = mapped_column(String(128))
    expected_direction: Mapped[str | None] = mapped_column(String(32))

    invalidation_rule: Mapped[str | None] = mapped_column(
        Text, comment="失效条件文本，不可由 AI 直接生效（FLD-005）"
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="待验证")
    owner_note: Mapped[str | None] = mapped_column(Text)
    confirmed_by: Mapped[str | None] = mapped_column(String(64))
    confirmed_at: Mapped[datetime | None] = mapped_column()

    thesis: Mapped[Thesis] = relationship(back_populates="hypotheses")

    __table_args__ = (Index("ix_hypothesis_thesis_id", "thesis_id"),)


class Metric(Base):
    """指标字典。所有预期差、趋势和同业比较均从此表读取口径。

    口径变更必须创建新版本，不直接覆盖历史口径，因此主键为 (metric_id, version)。
    """

    __tablename__ = "metric"

    metric_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[str] = mapped_column(String(16), primary_key=True, default="v1.0")

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64))
    definition: Mapped[str | None] = mapped_column(Text)
    formula: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    frequency: Mapped[str | None] = mapped_column(String(32))
    period_type: Mapped[str] = mapped_column(String(16), nullable=False, default="单季度")
    source_id: Mapped[str | None] = mapped_column(String(64))
    expected_direction: Mapped[str | None] = mapped_column(String(32))

    allow_yoy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_qoq: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_peer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    missing_policy: Mapped[str | None] = mapped_column(Text)
    confirmed_by: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="待确认")


class MetricAlias(Base):
    """指标 ID 别名映射。

    交付包存在两套命名：指标字典用 MET-001~005，台账与样例 CSV 用
    MET-DEMO-001~003。导入时必须先解析别名，否则假设-指标映射会断链。
    """

    __tablename__ = "metric_alias"

    alias: Mapped[str] = mapped_column(String(64), primary_key=True)
    metric_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_note: Mapped[str | None] = mapped_column(String(255))


class HypothesisMetricMap(Base):
    """假设—指标映射。定义每条假设如何被数据验证。禁止无来源自动生效。"""

    __tablename__ = "hypothesis_metric_map"

    mapping_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hypothesis_id: Mapped[str] = mapped_column(
        ForeignKey("hypothesis.hypothesis_id", ondelete="CASCADE"), nullable=False
    )
    metric_id: Mapped[str] = mapped_column(String(64), nullable=False)
    metric_version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1.0")

    metric_role: Mapped[str | None] = mapped_column(String(16))
    expected_direction: Mapped[str] = mapped_column(String(32), nullable=False)
    expected_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    expected_lower: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    expected_upper: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    expectation_source: Mapped[str | None] = mapped_column(
        String(255), comment="预期来源，预期差计算要求可追溯（GAP-002）"
    )
    expectation_recorded_at: Mapped[datetime | None] = mapped_column()

    validation_rule: Mapped[str | None] = mapped_column(Text)
    invalidation_rule: Mapped[str | None] = mapped_column(Text)
    invalidation_threshold: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    observation_frequency: Mapped[str | None] = mapped_column(String(32))

    confirmation_status: Mapped[str] = mapped_column(String(16), nullable=False, default="待确认")
    confirmed_by: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1.0")

    __table_args__ = (Index("ix_hmm_hypothesis_id", "hypothesis_id"),)


class MetricObservation(Base):
    """指标观测值。同时保留原始值与归一值，单位口径不一致禁止混算。"""

    __tablename__ = "metric_observation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    security_id: Mapped[str] = mapped_column(String(64), nullable=False)
    metric_id: Mapped[str] = mapped_column(String(64), nullable=False)
    metric_version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1.0")

    period: Mapped[str] = mapped_column(String(32), nullable=False)
    period_type: Mapped[str] = mapped_column(String(16), nullable=False, default="单季度")
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)

    actual_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    raw_value: Mapped[str | None] = mapped_column(String(64))
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    expected_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    benchmark_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))

    source_document_id: Mapped[str | None] = mapped_column(String(64))
    data_version: Mapped[str | None] = mapped_column(String(64))
    is_illustrative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ingested_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        UniqueConstraint("security_id", "metric_id", "metric_version", "period", "data_version"),
        Index("ix_metric_obs_lookup", "security_id", "metric_id", "observation_date"),
    )


class Event(Base):
    """结构化事件。事实发生时间与首次公开时间必须分离存储。"""

    __tablename__ = "event"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("document.document_id"))
    security_id: Mapped[str | None] = mapped_column(ForeignKey("security.security_id"))

    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)

    occurred_on: Mapped[date | None] = mapped_column(Date, comment="事实发生时间，无法确认时可为空")
    disclosure_time: Mapped[datetime] = mapped_column(
        nullable=False, comment="首次公开可得时间，必填（FLD-006）；防未来数据泄露关键字段"
    )
    ingested_at: Mapped[datetime] = created_at_column()

    fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="事件指纹，同一事实多源转载去重"
    )
    source_document_ids: Mapped[list | None] = mapped_column(
        JSONB, comment="重复事件合并后保留的来源集合（FR-R-005）"
    )
    version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1.0")
    is_illustrative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("fingerprint"),
        Index("ix_event_disclosure_time", "disclosure_time"),
    )


class Evidence(Base):
    """证据。只有 confirmation_status = 已确认 才进入正式证据链并参与状态计算。"""

    __tablename__ = "evidence"

    evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    security_id: Mapped[str | None] = mapped_column(String(64), index=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("event.event_id"))
    thesis_id: Mapped[str] = mapped_column(
        ForeignKey("thesis.thesis_id", ondelete="CASCADE"), nullable=False
    )
    hypothesis_id: Mapped[str] = mapped_column(
        ForeignKey("hypothesis.hypothesis_id"),
        nullable=False,
        comment="至少关联一条假设；方向相对假设判断，不是通用情绪",
    )

    evidence_type: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    strength: Mapped[str | None] = mapped_column(String(16))
    strength_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    horizon: Mapped[str | None] = mapped_column(String(16))
    is_direct: Mapped[bool | None] = mapped_column(Boolean)

    evidence_locator: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="必须能打开原文，格式 {document_id}#paragraph-{n}",
    )
    transmission_path: Mapped[str | None] = mapped_column(Text)
    fact_excerpt: Mapped[str | None] = mapped_column(Text)
    source_document_id: Mapped[str | None] = mapped_column(String(64))
    source_document_title: Mapped[str | None] = mapped_column(String(512))
    disclosed_at: Mapped[datetime | None] = mapped_column()
    occurred_at: Mapped[date | None] = mapped_column(Date)
    source_url: Mapped[str | None] = mapped_column(String(2048))

    ai_status: Mapped[str | None] = mapped_column(String(16))
    ai_confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    model_version: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(64))

    confirmation_status: Mapped[str] = mapped_column(String(16), nullable=False, default="待确认")
    review_status: Mapped[str | None] = mapped_column(String(16))
    review_note: Mapped[str | None] = mapped_column(Text)
    confirmed_by: Mapped[str | None] = mapped_column(String(64))
    confirmed_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        Index("ix_evidence_thesis", "thesis_id", "confirmation_status"),
        Index("ix_evidence_hypothesis", "hypothesis_id"),
    )


class EvidenceRelation(Base):
    """证据与逻辑假设的独立关联。

    Evidence 保存不可修改的来源事实；关联可在同一证券范围内扩展、审核和解除。
    避免直接覆写 Evidence 上的旧单关联字段，保留历史兼容与审计可追溯性。
    """

    __tablename__ = "evidence_relation"

    relation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence.evidence_id", ondelete="CASCADE"), nullable=False
    )
    thesis_id: Mapped[str] = mapped_column(
        ForeignKey("thesis.thesis_id", ondelete="CASCADE"), nullable=False
    )
    hypothesis_id: Mapped[str] = mapped_column(
        ForeignKey("hypothesis.hypothesis_id"), nullable=False
    )
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    strength: Mapped[str | None] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="待确认")
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(64))
    reviewed_at: Mapped[datetime | None] = mapped_column()
    deactivated_by: Mapped[str | None] = mapped_column(String(64))
    deactivated_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        Index("ix_evidence_relation_evidence", "evidence_id", "status"),
        Index("ix_evidence_relation_thesis", "thesis_id", "status"),
    )


class Signal(Base):
    """AI 候选信号。不是交易指令。必须绑定事件、逻辑、假设、生成时间和模型版本。"""

    __tablename__ = "signal"

    signal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("event.event_id"))
    thesis_id: Mapped[str | None] = mapped_column(ForeignKey("thesis.thesis_id"))
    hypothesis_id: Mapped[str | None] = mapped_column(ForeignKey("hypothesis.hypothesis_id"))
    security_id: Mapped[str] = mapped_column(String(64), nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    direction: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="对关联假设的影响方向，不等于股价方向"
    )
    strength: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    horizon: Mapped[str | None] = mapped_column(String(16))
    rationale: Mapped[str | None] = mapped_column(Text)

    available_at: Mapped[datetime] = mapped_column(
        nullable=False, comment="首次可得时间，收益窗口起点依据"
    )
    generated_at: Mapped[datetime] = mapped_column(
        nullable=False, comment="模型生成时间；必须晚于或等于披露时间（DQ-003）"
    )
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)

    evidence_locator: Mapped[str | None] = mapped_column(
        String(255), comment="DQ-005：正式信号必须有证据定位和模型版本"
    )
    human_verdict: Mapped[str | None] = mapped_column(String(16))
    human_direction: Mapped[str | None] = mapped_column(String(16))
    reject_reason: Mapped[str | None] = mapped_column(Text)
    in_experiment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1.0")
    is_illustrative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        CheckConstraint("generated_at >= available_at", name="no_future_leakage"),
        Index("ix_signal_generated_at", "generated_at"),
    )


class Outcome(Base):
    """结果标签。窗口标签只能在窗口结束后生成（DQ-006）。"""

    __tablename__ = "outcome"

    outcome_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    signal_id: Mapped[str] = mapped_column(
        ForeignKey("signal.signal_id", ondelete="CASCADE"), nullable=False
    )
    security_id: Mapped[str] = mapped_column(String(64), nullable=False)

    window_start_on: Mapped[date] = mapped_column(
        Date, nullable=False, comment="首次可得时间的下一可交易时点"
    )
    window_end_on: Mapped[date] = mapped_column(Date, nullable=False)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=20)

    state: Mapped[str] = mapped_column(String(16), nullable=False, default="待观察")
    fundamental_result: Mapped[str | None] = mapped_column(Text)
    fundamental_realized: Mapped[str | None] = mapped_column(String(16))

    security_return: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    benchmark_return: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    excess_return: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    benchmark_id: Mapped[str | None] = mapped_column(String(64))
    is_hit: Mapped[bool | None] = mapped_column(Boolean)

    label_generated_at: Mapped[date | None] = mapped_column(Date)
    data_version: Mapped[str | None] = mapped_column(String(64))
    is_illustrative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        CheckConstraint("window_end_on >= window_start_on", name="window_order"),
        CheckConstraint(
            "label_generated_at IS NULL OR label_generated_at >= window_end_on",
            name="no_label_before_window_end",
        ),
    )


class Experiment(Base):
    """实验记录。未固化版本不得发布结论。"""

    __tablename__ = "experiment"

    experiment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    economic_hypothesis: Mapped[str] = mapped_column(
        Text, nullable=False, comment="必须先写经济假设再看结果"
    )
    signal_type: Mapped[str | None] = mapped_column(String(64))

    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    dataset_version: Mapped[str] = mapped_column(String(64), nullable=False)
    baseline_name: Mapped[str] = mapped_column(String(128), nullable=False)

    in_sample_range: Mapped[str | None] = mapped_column(String(64))
    out_sample_range: Mapped[str | None] = mapped_column(String(64))
    sample_size: Mapped[int | None] = mapped_column(
        Integer, comment="仅有百分比、没有样本数的结果不得用于验收"
    )

    metrics: Mapped[dict | None] = mapped_column(JSONB)
    conclusion_level: Mapped[str] = mapped_column(String(32), nullable=False, default="探索性")
    limitations: Mapped[str] = mapped_column(Text, nullable=False, comment="必须披露限制与失败案例")
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="进行中")
    created_at: Mapped[datetime] = created_at_column()
