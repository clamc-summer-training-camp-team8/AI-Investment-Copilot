"""跨层共享的值对象。

放在 app.core 是分层契约的要求：`app/db/repositories` 构造这些对象，
`app/services` 消费它们，而 app.db 位于 app.services 之下，不能反向 import。
放在这里两边都能用，且不引入反向依赖。

这些是**值对象，不是 ORM 模型**。服务层不 import app.db.models，避免编排逻辑
与表结构耦合；仓储负责两者之间的转换。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from app.core.enums import (
    ConfirmationStatus,
    ExpectationDirection,
    ImpactDirection,
    Importance,
    ReviewStatus,
    ThesisStatus,
)


@dataclass
class SecurityRecord:
    """证券主数据。新建标的先建档，再允许逻辑和文档引用。"""

    security_id: str
    name: str
    ticker: str | None = None
    industry: str | None = None
    aliases: list[str] = field(default_factory=list)
    is_illustrative: bool = False


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    name: str
    source_type: str
    authorization_status: str = "待确认"
    base_url: str | None = None
    license_note: str | None = None
    active: bool = True


@dataclass(frozen=True)
class IndustryRecord:
    industry_id: str
    name: str
    parent_id: str | None = None


@dataclass(frozen=True)
class SecurityIndustryMembershipRecord:
    security_id: str
    industry_id: str
    valid_from: date
    valid_to: date | None = None
    source_id: str | None = None


@dataclass(frozen=True)
class DocumentSecurityRelationRecord:
    document_id: str
    security_id: str
    relation_type: str = "主体"
    status: str = "已确认"
    confidence: Decimal | None = None
    created_by: str = "system"


@dataclass
class EventRecord:
    """上传资料中持久化的结构化事件。"""

    event_id: str
    document_id: str | None
    security_id: str | None
    event_type: str
    summary: str
    disclosure_time: datetime
    fingerprint: str
    occurred_on: date | None = None
    source_document_ids: list[str] = field(default_factory=list)
    version: str = "v1.0"
    is_illustrative: bool = False


@dataclass
class ThesisRecord:
    thesis_id: str
    security_id: str
    title: str
    direction: str
    core_view: str
    established_on: date
    owner: str
    status: ThesisStatus = ThesisStatus.DRAFT
    visibility: str = "团队"
    version: int = 0
    is_current: bool = True
    superseded_by_thesis_id: str | None = None
    team: str | None = None
    horizon_end_on: date | None = None
    next_review_at: date | None = None
    source_document_id: str | None = None
    is_illustrative: bool = False
    # 失效条件是「全部满足」还是「任一满足」。样例案例为 AND。
    invalidation_require_all: bool = True
    # 参与 thesis 级失效条件的假设。为空表示全部参与。
    #
    # 样例案例的失效条件只写了收入与毛利率两条，没提行业装机。把不在条件里的
    # 假设也算进 AND，会让一条长期达标的假设永久压住失效判定。
    invalidation_hypotheses: list[str] = field(default_factory=list)
    # AI 生成的指标、风险与失效建议只作为待采用候选保存，不能直接改变正式配置。
    draft_suggestions: dict[str, object] = field(default_factory=dict)
    thesis_kind: str = "canonical"
    thesis_series_id: str | None = None


@dataclass
class HypothesisRecord:
    hypothesis_id: str
    thesis_id: str
    statement: str
    hypothesis_type: str
    importance: Importance
    name: str | None = None
    weight: Decimal | None = None
    observation_window: str | None = None
    expected_direction: ExpectationDirection | None = None
    invalidation_rule: str | None = None
    status: str = "待验证"


@dataclass
class MetricMappingRecord:
    """假设—指标映射。

    `invalidation_consecutive_periods` 逐条可配：样例里 H1/H2 要求连续两期，
    H3「毛利率低于 18%」单期即标记风险。全局默认值表达不了这个差异。
    """

    mapping_id: str
    hypothesis_id: str
    metric_id: str
    expected_direction: ExpectationDirection
    metric_version: str = "v1.0"
    expected_value: Decimal | None = None
    invalidation_threshold: Decimal | None = None
    invalidation_consecutive_periods: int | None = None
    expectation_source: str | None = None
    confirmation_status: ConfirmationStatus = ConfirmationStatus.PENDING


@dataclass(frozen=True)
class MetricDefinitionRecord:
    """可搜索的指标字典条目；口径按 metric_id + version 不可变。"""

    metric_id: str
    version: str
    name: str
    unit: str
    category: str | None = None
    definition: str | None = None
    frequency: str | None = None
    period_type: str = "单季度"
    source_id: str | None = None
    expected_direction: ExpectationDirection | None = None
    status: str = "待确认"


@dataclass
class EvidenceRecord:
    evidence_id: str
    thesis_id: str
    hypothesis_id: str
    evidence_type: str
    direction: ImpactDirection
    evidence_locator: str
    event_id: str | None = None
    strength: str | None = None
    strength_score: Decimal | None = None
    horizon: str | None = None
    ai_status: str | None = None
    ai_confidence: Decimal | None = None
    model_version: str | None = None
    prompt_version: str | None = None
    confirmation_status: ConfirmationStatus = ConfirmationStatus.PENDING
    review_status: ReviewStatus = ReviewStatus.PENDING
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    review_note: str | None = None
    # 来源文档的权限标签，随证据走。确认时用于校验「证据可见性不得高于来源文档」。
    source_visibility_label: str = "内部"
    # 详情字段必须随证据持久化，不能由前端拼接或依赖易变的外部页面。
    security_id: str | None = None
    fact_excerpt: str | None = None
    source_document_id: str | None = None
    source_document_title: str | None = None
    disclosed_at: datetime | None = None
    occurred_at: date | None = None
    source_url: str | None = None
    # 证据生成时冻结的检索追踪；只包含分数、路径和快照清单，不复制原文正文。
    retrieval_trace: dict[str, object] | None = None
    ingested_at: datetime | None = None


@dataclass
class EvidenceRelationRecord:
    """独立关联值对象；状态只作用于本条逻辑—假设关系。"""

    relation_id: str
    evidence_id: str
    thesis_id: str
    hypothesis_id: str
    direction: ImpactDirection
    strength: str | None
    status: ConfirmationStatus
    created_by: str
    reason: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    deactivated_by: str | None = None
    deactivated_at: datetime | None = None


@dataclass
class EvidenceFeedRecord:
    """面向研究员列表的可读证据聚合，不作为新的持久化实体。"""

    evidence_id: str
    relation_id: str
    security_id: str
    security_name: str
    thesis_id: str
    thesis_title: str
    thesis_owner: str
    thesis_status: ThesisStatus
    thesis_established_on: date
    thesis_horizon_end_on: date | None
    hypothesis_id: str
    hypothesis_statement: str
    hypothesis_importance: Importance
    source_document_id: str | None
    source_document_title: str | None
    fact_excerpt: str | None
    disclosed_at: datetime | None
    occurred_at: date | None
    source_url: str | None
    direction: ImpactDirection
    strength: str | None
    ai_confidence: Decimal | None
    confirmation_status: ConfirmationStatus
    priority: str


@dataclass
class ObservationRecord:
    security_id: str
    metric_id: str
    period: str
    observation_date: date
    unit: str
    actual_value: Decimal | None = None
    expected_value: Decimal | None = None
    benchmark_value: Decimal | None = None
    metric_version: str = "v1.0"
    period_type: str = "单季度"
    source_document_id: str | None = None
    data_version: str | None = None
    ingested_at: datetime | None = None


@dataclass
class SuggestionRecord:
    thesis_id: str
    current_status: ThesisStatus
    suggested_status: ThesisStatus
    reasons: list[str]
    rule_version: str
    triggered_hypotheses: list[str] = field(default_factory=list)
    human_action: str | None = None
    human_reason: str | None = None
    acted_by: str | None = None
    # 处置时间。建议生成到人工确认的时延是北极星指标的输入，不能只留在审计表里
    acted_at: datetime | None = None
    suggestion_id: int | None = None


@dataclass
class VersionRecord:
    thesis_id: str
    version: int
    snapshot: dict[str, object]
    triggered_by: str
    created_by: str
    change_reason: str | None = None
    changed_fields: list[str] = field(default_factory=list)
    data_cutoff_at: datetime | None = None
    rule_version: str | None = None
    model_versions: list[str] = field(default_factory=list)


@dataclass
class AuditRecord:
    actor: str
    action: str
    object_type: str
    object_id: str
    detail: dict[str, object] | None = None
    model_version: str | None = None
    # 写入时由数据库填充，读出来才有值。留痕页必须显示时间，否则「谁在何时改了什么」
    # 只剩下「谁改了什么」。
    occurred_at: datetime | None = None


@dataclass(frozen=True)
class ThesisQuery:
    """卡片列表查询条件。

    `limit` 有上限：列表接口禁止无上限查询（contracts/api/README.md，对齐
    PRD 12.2 的列表 P95 <= 2 秒）。上限在服务层校验，这里只承载条件。

    `statuses` 与 `securities` 为空表示不过滤该维度，不是「过滤掉全部」——
    空列表当成全不匹配会让默认查询返回空页。
    """

    statuses: tuple[ThesisStatus, ...] = ()
    securities: tuple[str, ...] = ()
    owner: str | None = None
    keyword: str | None = None
    limit: int = 20
    offset: int = 0
    include_snapshots: bool = False


@dataclass
class ReviewTaskRecord:
    task_id: str
    thesis_id: str
    trigger: str
    priority: str
    assignee: str
    state: str = "待处理"
    detail: dict[str, object] | None = None
    resolution: str | None = None
    created_at: datetime | None = None
    resolved_at: datetime | None = None


@dataclass
class DocumentProcessingJobRecord:
    """可重放的资料处理任务；Redis 只承载执行，不再是任务事实源。"""

    job_id: str
    document_id: str
    owner: str
    upload_path: str | None
    source_filename: str
    published_at: datetime | None
    revision_id: str | None = None
    object_key: str | None = None
    object_version_id: str | None = None
    upload_content_hash: str | None = None
    ingestion_run_id: str | None = None
    actor_teams: list[str] = field(default_factory=list)
    security_id: str | None = None
    thesis_id: str | None = None
    view: str = ""
    status: str = "queued"
    attempt_count: int = 1
    max_attempts: int = 3
    result: dict[str, object] | None = None
    last_error: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class IngestionReviewRecord:
    """不依赖投资逻辑的资料复核项，覆盖归属、匹配、置信度与处理失败。"""

    review_id: str
    dedupe_key: str
    review_type: str
    document_id: str
    reason: str
    assignee: str
    job_id: str | None = None
    event_id: str | None = None
    status: str = "pending"
    payload: dict[str, object] = field(default_factory=dict)
    security_candidates: list[dict[str, object]] = field(default_factory=list)
    resolution: str | None = None
    resolved_by: str | None = None
    created_at: datetime | None = None
    resolved_at: datetime | None = None


@dataclass
class DocumentRecord:
    """可检索、可审计的文档元数据。正文与段落必须同事务持久化。"""

    document_id: str
    published_at: datetime
    content_hash: str
    parser_version: str
    title: str | None = None
    source_id: str | None = None
    doc_type: str | None = None
    security_id: str | None = None
    raw_path: str | None = None
    body: str | None = None
    visibility_label: str = "内部"
    is_illustrative: bool = False
    ingested_at: datetime | None = None
    deleted_at: datetime | None = None


@dataclass
class DocumentRevisionRecord:
    revision_id: str
    document_id: str
    content_hash: str
    source_filename: str
    object_key: str | None = None
    object_version_id: str | None = None
    canonical_document_id: str | None = None
    media_type: str | None = None
    byte_size: int | None = None
    source_id: str | None = None
    source_url: str | None = None
    authorization_status: str = "待确认"
    uploaded_by: str = "system"
    published_at: datetime | None = None
    created_at: datetime | None = None
    tombstoned_at: datetime | None = None


@dataclass
class IngestionRunRecord:
    run_id: str
    revision_id: str
    parser_version: str
    chunker_version: str
    extractor_version: str
    embedding_version: str | None = None
    status: str = "queued"
    segment_count: int = 0
    fact_count: int = 0
    event_count: int = 0
    quality_summary: dict[str, object] = field(default_factory=dict)
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class IngestionArtifactRecord:
    run_id: str
    artifact_type: str
    artifact_key: str
    payload: dict[str, object]
    content_hash: str


@dataclass
class ThesisRevisionDraftRecord:
    draft_id: str
    thesis_id: str
    base_version: int
    revision: int
    owner: str
    payload: dict[str, object]
    status: str = "editing"
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class AssetSearchHitRecord:
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
    published_at: datetime | None = None
    source: str = ""


@dataclass(frozen=True)
class EmbeddingSourceRecord:
    index_id: str
    ingestion_run_id: str | None
    document_id: str
    locator: str
    content: str


@dataclass(frozen=True)
class SegmentEmbeddingRecord:
    index_id: str
    ingestion_run_id: str | None
    document_id: str
    locator: str
    embedding_version: str
    embedding: list[float]


@dataclass(frozen=True)
class DocumentSegmentRecord:
    document_id: str
    locator: str
    ordinal: int
    content: str
    page: int | None = None
    content_kind: str = "paragraph"
    extraction_method: str = "native"
    table_index: int | None = None
    row_index: int | None = None
    cell_range: str | None = None
    confidence: Decimal | None = None


@dataclass(frozen=True)
class DocumentFactRecord:
    """从正文确定性抽取的最小事实；不等同于正式投资证据。"""

    fact_id: str
    document_id: str
    locator: str
    fact_type: str
    metric_name: str
    direction: str
    raw_text: str
    extraction_version: str
    change_rate_low: Decimal | None = None
    change_rate_high: Decimal | None = None


@dataclass
class AdjudicationDecisionRecord:
    event_id: str
    hypothesis: str
    direction: str
    reason: str
    decided_by: str
    decided_at: datetime | None = None


@dataclass(frozen=True)
class RankingPriorSnapshotRecord:
    snapshot_id: str
    security_id: str
    direction: str
    horizon: str
    as_of: datetime
    ranker_version: str
    feature_version: str
    status: str = "generated"
    generator_model_version: str | None = None
    judge_model_version: str | None = None
    prompt_version: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass(frozen=True)
class RankingPriorItemRecord:
    snapshot_id: str
    object_type: str
    object_id: str
    base_rank: int
    base_score: Decimal
    final_rank: int
    final_score: Decimal
    feature_scores: dict[str, float] = field(default_factory=dict)
    reason_codes: list[str] = field(default_factory=list)
    citation_locators: list[str] = field(default_factory=list)
    status: str = "active"
    judge_rank: int | None = None
    judge_score: Decimal | None = None
    judge_confidence: Decimal | None = None


@dataclass(frozen=True)
class LogicTopicRecord:
    topic_id: str
    security_id: str
    name: str
    normalized_statement: str
    direction: str
    horizon: str
    status: str = "active"
    topic_version: str = "v1"
    source_thesis_ids: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass(frozen=True)
class LogicTopicRelationRecord:
    relation_id: str
    topic_id: str
    object_type: str
    object_id: str
    relation: str
    confidence: Decimal
    source: str
    reason: str | None = None
    citation_locators: list[str] = field(default_factory=list)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    model_version: str | None = None
    prompt_version: str | None = None
    status: str = "active"
    created_at: datetime | None = None


class RankingPriorRepo(Protocol):
    def upsert_topics(self, records: list[LogicTopicRecord]) -> None: ...
    def upsert_topic_relations(self, records: list[LogicTopicRelationRecord]) -> None: ...
    def topics(
        self, *, security_id: str, direction: str, horizon: str
    ) -> list[LogicTopicRecord]: ...
    def topic_relations(self, topic_id: str) -> list[LogicTopicRelationRecord]: ...
    def add_snapshot(self, record: RankingPriorSnapshotRecord) -> None: ...
    def get_snapshot(self, snapshot_id: str) -> RankingPriorSnapshotRecord | None: ...
    def update_snapshot_status(self, snapshot_id: str, status: str) -> None: ...
    def active_snapshot(
        self,
        *,
        security_id: str,
        direction: str,
        horizon: str,
        as_of: datetime | None,
    ) -> RankingPriorSnapshotRecord | None: ...
    def add_items(self, records: list[RankingPriorItemRecord]) -> None: ...
    def items_for_objects(
        self, snapshot_id: str, *, object_type: str, object_ids: tuple[str, ...]
    ) -> list[RankingPriorItemRecord]: ...
    def ranked_items(
        self, snapshot_id: str, *, object_type: str, limit: int
    ) -> list[RankingPriorItemRecord]: ...


class SecurityRepo(Protocol):
    def get(self, security_id: str) -> SecurityRecord | None: ...
    def add(self, record: SecurityRecord) -> None: ...
    def search(self, keyword: str | None = None, *, limit: int = 100) -> list[SecurityRecord]: ...


class AssetRepo(Protocol):
    def add_source(self, record: SourceRecord) -> None: ...
    def get_source(self, source_id: str) -> SourceRecord | None: ...
    def add_industry(self, record: IndustryRecord) -> None: ...
    def get_industry_by_name(self, name: str) -> IndustryRecord | None: ...
    def add_membership(self, record: SecurityIndustryMembershipRecord) -> None: ...
    def add_document_security(self, record: DocumentSecurityRelationRecord) -> None: ...
    def add_revision(self, record: DocumentRevisionRecord) -> None: ...
    def get_revision(self, revision_id: str) -> DocumentRevisionRecord | None: ...
    def find_revision_by_hash(self, content_hash: str) -> DocumentRevisionRecord | None: ...
    def document_id_by_source_url(self, source_url: str) -> str | None: ...
    def update_revision(self, record: DocumentRevisionRecord) -> None: ...
    def add_run(self, record: IngestionRunRecord) -> None: ...
    def get_run(self, run_id: str) -> IngestionRunRecord | None: ...
    def update_run(self, record: IngestionRunRecord) -> None: ...
    def latest_run(self, revision_id: str) -> IngestionRunRecord | None: ...
    def add_artifacts(self, records: list[IngestionArtifactRecord]) -> None: ...
    def index_artifacts(
        self,
        *,
        run_id: str,
        document_id: str,
        visibility_label: str,
        records: list[IngestionArtifactRecord],
    ) -> None: ...
    def inventory(self) -> dict[str, int]: ...
    def add_thesis_revision(self, record: ThesisRevisionDraftRecord) -> None: ...
    def get_thesis_revision(self, draft_id: str) -> ThesisRevisionDraftRecord | None: ...
    def active_thesis_revision(self, thesis_id: str) -> ThesisRevisionDraftRecord | None: ...
    def update_thesis_revision(self, record: ThesisRevisionDraftRecord) -> None: ...
    def rebuild_search_index(self) -> int: ...
    def sync_document_visibility(self, document_id: str, visibility_label: str) -> None: ...
    def remove_document_from_index(self, document_id: str) -> None: ...
    def tombstone_revisions(self, document_id: str, tombstoned_at: datetime) -> None: ...
    def search_segments(
        self, *, query: str, visibility_labels: tuple[str, ...], limit: int
    ) -> list[AssetSearchHitRecord]: ...
    def pending_embedding_sources(
        self, *, embedding_version: str, limit: int
    ) -> list[EmbeddingSourceRecord]: ...
    def upsert_embeddings(self, records: list[SegmentEmbeddingRecord]) -> int: ...
    def hybrid_search_segments(
        self,
        *,
        query: str,
        query_embedding: list[float],
        embedding_version: str,
        visibility_labels: tuple[str, ...],
        security_ids: tuple[str, ...],
        industries: tuple[str, ...],
        published_from: datetime | None,
        published_to: datetime | None,
        keyword_weight: float,
        vector_weight: float,
        limit: int,
    ) -> list[AssetSearchHitRecord]: ...


class EventRepo(Protocol):
    def get(self, event_id: str) -> EventRecord | None: ...
    def find_by_fingerprint(self, fingerprint: str) -> EventRecord | None: ...
    def add(self, record: EventRecord) -> None: ...
    def update(self, record: EventRecord) -> None: ...


class ThesisRepo(Protocol):
    def get(self, thesis_id: str) -> ThesisRecord | None: ...
    def add(self, record: ThesisRecord) -> None: ...
    def update(self, record: ThesisRecord) -> None: ...
    def list_hypotheses(self, thesis_id: str) -> list[HypothesisRecord]: ...
    def get_hypothesis(self, hypothesis_id: str) -> HypothesisRecord | None: ...
    def add_hypothesis(self, record: HypothesisRecord) -> None: ...
    def update_hypothesis(self, record: HypothesisRecord) -> None: ...
    def list_mappings(self, hypothesis_id: str) -> list[MetricMappingRecord]: ...
    def add_mapping(self, record: MetricMappingRecord) -> None: ...
    def update_mapping(self, record: MetricMappingRecord) -> None: ...
    def get_by_security(self, security_id: str) -> ThesisRecord | None: ...
    def search(self, query: ThesisQuery) -> tuple[list[ThesisRecord], int]: ...

    """按条件分页查询，返回（当页记录, 满足条件的总数）。

    总数与当页一起返回，否则前端无法渲染分页器。可见性过滤不在这里做——
    那是业务规则，属于 app/services。
    """


class MetricRepo(Protocol):
    def get(self, metric_id: str, version: str = "v1.0") -> MetricDefinitionRecord | None: ...
    def search(
        self, keyword: str | None = None, *, limit: int = 50
    ) -> list[MetricDefinitionRecord]: ...


class EvidenceRepo(Protocol):
    def get(self, evidence_id: str) -> EvidenceRecord | None: ...
    def add(self, record: EvidenceRecord) -> None: ...
    def update(self, record: EvidenceRecord) -> None: ...
    def list_for_thesis(self, thesis_id: str) -> list[EvidenceRecord]: ...


class EvidenceRelationRepo(Protocol):
    def get(self, relation_id: str) -> EvidenceRelationRecord | None: ...
    def list_for_evidence(self, evidence_id: str) -> list[EvidenceRelationRecord]: ...
    def list_for_thesis(self, thesis_id: str) -> list[EvidenceRelationRecord]: ...
    def add(self, record: EvidenceRelationRecord) -> None: ...
    def update(self, record: EvidenceRelationRecord) -> None: ...


class EvidenceFeedRepo(Protocol):
    def search(
        self,
        *,
        thesis_ids: tuple[str, ...],
        statuses: tuple[ConfirmationStatus, ...] = (),
        direction: ImpactDirection | None = None,
        priorities: tuple[str, ...] = (),
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[EvidenceFeedRecord], int]: ...


class ObservationRepo(Protocol):
    def list_for_metric(self, security_id: str, metric_id: str) -> list[ObservationRecord]: ...
    def add(self, record: ObservationRecord) -> None: ...


class SuggestionRepo(Protocol):
    def add(self, record: SuggestionRecord) -> SuggestionRecord: ...
    def get(self, suggestion_id: int) -> SuggestionRecord | None: ...
    def update(self, record: SuggestionRecord) -> None: ...
    def list_for_thesis(self, thesis_id: str) -> list[SuggestionRecord]: ...


class VersionRepo(Protocol):
    def add(self, record: VersionRecord) -> None: ...
    def latest(self, thesis_id: str) -> VersionRecord | None: ...
    def list_for_thesis(self, thesis_id: str) -> list[VersionRecord]: ...


class AuditRepo(Protocol):
    def add(self, record: AuditRecord) -> None: ...
    def list_for_object(self, object_type: str, object_id: str) -> list[AuditRecord]: ...
    def page_for_object(
        self, object_type: str, object_id: str, *, limit: int, offset: int
    ) -> tuple[list[AuditRecord], int]: ...


class ReviewTaskRepo(Protocol):
    def add(self, record: ReviewTaskRecord) -> ReviewTaskRecord: ...
    def get(self, task_id: str) -> ReviewTaskRecord | None: ...
    def update(self, record: ReviewTaskRecord) -> None: ...
    def list_for_assignee(
        self, assignee: str, *, state: str | None = None, limit: int = 100
    ) -> list[ReviewTaskRecord]: ...


class DocumentProcessingJobRepo(Protocol):
    def add(self, record: DocumentProcessingJobRecord) -> None: ...
    def get(self, job_id: str) -> DocumentProcessingJobRecord | None: ...
    def get_by_document(self, document_id: str) -> DocumentProcessingJobRecord | None: ...
    def update(self, record: DocumentProcessingJobRecord) -> None: ...
    def list_for_owner(
        self, owner: str, *, status: str | None = None, limit: int = 100
    ) -> list[DocumentProcessingJobRecord]: ...
    def list_stale(
        self, *, before: datetime, statuses: tuple[str, ...]
    ) -> list[DocumentProcessingJobRecord]: ...


class IngestionReviewRepo(Protocol):
    def add(self, record: IngestionReviewRecord) -> IngestionReviewRecord: ...
    def get(self, review_id: str) -> IngestionReviewRecord | None: ...
    def get_by_dedupe_key(self, dedupe_key: str) -> IngestionReviewRecord | None: ...
    def update(self, record: IngestionReviewRecord) -> None: ...
    def list_for_assignee(
        self, assignee: str, *, status: str | None = None, limit: int = 100
    ) -> list[IngestionReviewRecord]: ...


class DocumentRepo(Protocol):
    def get(self, document_id: str) -> DocumentRecord | None: ...
    def find_by_content_hash(
        self, content_hash: str, parser_version: str
    ) -> DocumentRecord | None: ...
    def add(
        self,
        record: DocumentRecord,
        segments: list[DocumentSegmentRecord],
        facts: list[DocumentFactRecord],
    ) -> None: ...
    def update_security(self, document_id: str, security_id: str) -> None: ...
    def update_visibility(self, document_id: str, visibility_label: str) -> None: ...
    def mark_deleted(self, document_id: str, deleted_at: datetime) -> None: ...
    def list_segments(self, document_id: str) -> list[DocumentSegmentRecord]: ...
    def list_facts(self, document_id: str) -> list[DocumentFactRecord]: ...


class AdjudicationDecisionRepo(Protocol):
    def get(self, event_id: str) -> AdjudicationDecisionRecord | None: ...
    def add(self, record: AdjudicationDecisionRecord) -> AdjudicationDecisionRecord: ...


@dataclass
class UnitOfWork:
    """一次业务动作的仓储集合。

    业务写入与审计写入必须在同一事务内：审计缺失时业务动作应当回滚，否则
    FR-A-003 的可追溯性是空话（db/session.py 已有 session_scope 保证）。
    """

    securities: SecurityRepo
    events: EventRepo
    thesis: ThesisRepo
    metrics: MetricRepo
    evidence: EvidenceRepo
    relations: EvidenceRelationRepo
    feed: EvidenceFeedRepo
    observations: ObservationRepo
    suggestions: SuggestionRepo
    versions: VersionRepo
    audit: AuditRepo
    reviews: ReviewTaskRepo
    processing_jobs: DocumentProcessingJobRepo
    ingestion_reviews: IngestionReviewRepo
    documents: DocumentRepo
    adjudications: AdjudicationDecisionRepo
    assets: AssetRepo
    ranking: RankingPriorRepo
