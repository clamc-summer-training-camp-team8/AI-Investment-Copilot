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


class ThesisRepo(Protocol):
    def get(self, thesis_id: str) -> ThesisRecord | None: ...
    def add(self, record: ThesisRecord) -> None: ...
    def update(self, record: ThesisRecord) -> None: ...
    def list_hypotheses(self, thesis_id: str) -> list[HypothesisRecord]: ...
    def add_hypothesis(self, record: HypothesisRecord) -> None: ...
    def list_mappings(self, hypothesis_id: str) -> list[MetricMappingRecord]: ...
    def add_mapping(self, record: MetricMappingRecord) -> None: ...
    def find_by_security(self, security_id: str) -> list[ThesisRecord]: ...
    def search(self, query: ThesisQuery) -> tuple[list[ThesisRecord], int]: ...

    """按条件分页查询，返回（当页记录, 满足条件的总数）。

    总数与当页一起返回，否则前端无法渲染分页器。可见性过滤不在这里做——
    那是业务规则，属于 app/services。
    """


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


@dataclass
class UnitOfWork:
    """一次业务动作的仓储集合。

    业务写入与审计写入必须在同一事务内：审计缺失时业务动作应当回滚，否则
    FR-A-003 的可追溯性是空话（db/session.py 已有 session_scope 保证）。
    """

    thesis: ThesisRepo
    evidence: EvidenceRepo
    relations: EvidenceRelationRepo
    feed: EvidenceFeedRepo
    observations: ObservationRepo
    suggestions: SuggestionRepo
    versions: VersionRepo
    audit: AuditRepo
