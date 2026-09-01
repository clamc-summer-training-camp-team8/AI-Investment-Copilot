"""内存假仓储。

编排逻辑（状态流转、人工闸门、版本触发、权限判断）不该为了测试而必须起数据库。
真实 SQLAlchemy 仓储由 tests/integration 覆盖。

这些实现刻意保持"笨"：不加缓存、不做排序优化。假仓储一旦有自己的逻辑，测试就
可能通过假仓储的 bug 而不是被测代码的正确性。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from app.core.domain import (
    AdjudicationDecisionRecord,
    AuditRecord,
    DocumentFactRecord,
    DocumentProcessingJobRecord,
    DocumentRecord,
    DocumentRevisionRecord,
    DocumentSecurityRelationRecord,
    DocumentSegmentRecord,
    EventRecord,
    EvidenceFeedRecord,
    EvidenceRecord,
    EvidenceRelationRecord,
    HypothesisRecord,
    IndustryRecord,
    IngestionArtifactRecord,
    IngestionReviewRecord,
    IngestionRunRecord,
    MetricDefinitionRecord,
    MetricMappingRecord,
    ObservationRecord,
    RankingPriorItemRecord,
    RankingPriorSnapshotRecord,
    ReviewTaskRecord,
    SecurityIndustryMembershipRecord,
    SecurityRecord,
    SourceRecord,
    SuggestionRecord,
    ThesisQuery,
    ThesisRecord,
    ThesisRevisionDraftRecord,
    UnitOfWork,
    VersionRecord,
)
from app.core.enums import ExpectationDirection


class FakeAssetRepo:
    def __init__(self) -> None:
        self.sources: dict[str, SourceRecord] = {}
        self.industries: dict[str, IndustryRecord] = {}
        self.memberships: list[SecurityIndustryMembershipRecord] = []
        self.document_securities: list[DocumentSecurityRelationRecord] = []
        self.revisions: dict[str, DocumentRevisionRecord] = {}
        self.runs: dict[str, IngestionRunRecord] = {}
        self.artifacts: list[IngestionArtifactRecord] = []
        self.thesis_revisions: dict[str, ThesisRevisionDraftRecord] = {}

    def add_source(self, record: SourceRecord) -> None:
        self.sources[record.source_id] = record

    def get_source(self, source_id: str) -> SourceRecord | None:
        return self.sources.get(source_id)

    def add_industry(self, record: IndustryRecord) -> None:
        self.industries[record.industry_id] = record

    def get_industry_by_name(self, name: str) -> IndustryRecord | None:
        return next((item for item in self.industries.values() if item.name == name), None)

    def add_membership(self, record: SecurityIndustryMembershipRecord) -> None:
        self.memberships.append(record)

    def add_document_security(self, record: DocumentSecurityRelationRecord) -> None:
        if record not in self.document_securities:
            self.document_securities.append(record)

    def add_revision(self, record: DocumentRevisionRecord) -> None:
        self.revisions[record.revision_id] = replace(record)

    def get_revision(self, revision_id: str) -> DocumentRevisionRecord | None:
        record = self.revisions.get(revision_id)
        return None if record is None else replace(record)

    def find_revision_by_hash(self, content_hash: str) -> DocumentRevisionRecord | None:
        record = next((x for x in self.revisions.values() if x.content_hash == content_hash), None)
        return None if record is None else replace(record)

    def document_id_by_source_url(self, source_url: str) -> str | None:
        record = next((x for x in self.revisions.values() if x.source_url == source_url), None)
        return record.canonical_document_id if record else None

    def update_revision(self, record: DocumentRevisionRecord) -> None:
        self.revisions[record.revision_id] = replace(record)

    def add_run(self, record: IngestionRunRecord) -> None:
        self.runs[record.run_id] = replace(record)

    def get_run(self, run_id: str) -> IngestionRunRecord | None:
        record = self.runs.get(run_id)
        return None if record is None else replace(record)

    def update_run(self, record: IngestionRunRecord) -> None:
        self.runs[record.run_id] = replace(record)

    def latest_run(self, revision_id: str) -> IngestionRunRecord | None:
        records = [x for x in self.runs.values() if x.revision_id == revision_id]
        return replace(records[-1]) if records else None

    def add_artifacts(self, records: list[IngestionArtifactRecord]) -> None:
        self.artifacts.extend(records)

    def index_artifacts(
        self,
        *,
        run_id: str,
        document_id: str,
        visibility_label: str,
        records: list[IngestionArtifactRecord],
    ) -> None:
        return None

    def inventory(self) -> dict[str, int]:
        return {
            "documents": 0,
            "revisions": len(self.revisions),
            "ingestion_runs": len(self.runs),
            "segments": 0,
            "facts": 0,
            "single_segment_documents": 0,
            "semantic_runs": 0,
            "artifact_segments": sum(item.artifact_type == "segment" for item in self.artifacts),
            "artifact_facts": sum(item.artifact_type == "fact" for item in self.artifacts),
            "artifact_events": sum(item.artifact_type == "event" for item in self.artifacts),
            "pending_authorization": sum(
                item.authorization_status == "待确认" for item in self.revisions.values()
            ),
            "missing_object_archive": sum(
                item.object_key is None for item in self.revisions.values()
            ),
            "embeddings": 0,
        }

    def add_thesis_revision(self, record: ThesisRevisionDraftRecord) -> None:
        self.thesis_revisions[record.draft_id] = replace(record)

    def get_thesis_revision(self, draft_id: str) -> ThesisRevisionDraftRecord | None:
        record = self.thesis_revisions.get(draft_id)
        return None if record is None else replace(record)

    def active_thesis_revision(self, thesis_id: str) -> ThesisRevisionDraftRecord | None:
        record = next(
            (
                x
                for x in self.thesis_revisions.values()
                if x.thesis_id == thesis_id and x.status == "editing"
            ),
            None,
        )
        return None if record is None else replace(record)

    def update_thesis_revision(self, record: ThesisRevisionDraftRecord) -> None:
        self.thesis_revisions[record.draft_id] = replace(record)

    def rebuild_search_index(self) -> int:
        return 0

    def sync_document_visibility(self, document_id: str, visibility_label: str) -> None:
        return None

    def remove_document_from_index(self, document_id: str) -> None:
        return None

    def tombstone_revisions(self, document_id: str, tombstoned_at) -> None:
        for revision_id, record in list(self.revisions.items()):
            if record.canonical_document_id == document_id:
                self.revisions[revision_id] = replace(record, tombstoned_at=tombstoned_at)

    def search_segments(self, *, query: str, visibility_labels: tuple[str, ...], limit: int):
        return []

    def pending_embedding_sources(self, *, embedding_version: str, limit: int):
        return []

    def upsert_embeddings(self, records) -> int:
        return len(records)

    def hybrid_search_segments(self, **kwargs):
        return []


class FakeRankingPriorRepo:
    def __init__(self) -> None:
        self.snapshots: dict[str, RankingPriorSnapshotRecord] = {}
        self.items: dict[tuple[str, str, str], RankingPriorItemRecord] = {}
        self.logic_topics = {}
        self.logic_topic_relations = {}

    def upsert_topics(self, records) -> None:
        for row in records:
            self.logic_topics[row.topic_id] = replace(row)

    def upsert_topic_relations(self, records) -> None:
        for row in records:
            self.logic_topic_relations[row.relation_id] = replace(row)

    def topics(self, *, security_id, direction, horizon):
        return [
            replace(row)
            for row in self.logic_topics.values()
            if row.security_id == security_id
            and row.direction == direction
            and row.horizon == horizon
            and row.status == "active"
        ]

    def topic_relations(self, topic_id):
        return [
            replace(row)
            for row in self.logic_topic_relations.values()
            if row.topic_id == topic_id and row.status == "active"
        ]

    def add_snapshot(self, record: RankingPriorSnapshotRecord) -> None:
        self.snapshots[record.snapshot_id] = replace(record)

    def get_snapshot(self, snapshot_id: str) -> RankingPriorSnapshotRecord | None:
        record = self.snapshots.get(snapshot_id)
        return replace(record) if record else None

    def update_snapshot_status(self, snapshot_id: str, status: str) -> None:
        self.snapshots[snapshot_id] = replace(self.snapshots[snapshot_id], status=status)

    def active_snapshot(self, *, security_id, direction, horizon, as_of):
        rows = [
            row
            for row in self.snapshots.values()
            if row.security_id == security_id
            and row.direction == direction
            and row.horizon == horizon
            and row.status in {"provisional", "active", "active_experimental"}
            and (as_of is None or row.as_of <= as_of)
        ]
        return replace(max(rows, key=lambda row: row.as_of)) if rows else None

    def add_items(self, records: list[RankingPriorItemRecord]) -> None:
        for row in records:
            self.items[(row.snapshot_id, row.object_type, row.object_id)] = replace(row)

    def items_for_objects(self, snapshot_id, *, object_type, object_ids):
        return [
            replace(row)
            for object_id in object_ids
            if (row := self.items.get((snapshot_id, object_type, object_id))) is not None
            and row.status == "active"
        ]

    def ranked_items(self, snapshot_id, *, object_type, limit):
        rows = [
            replace(row)
            for row in self.items.values()
            if row.snapshot_id == snapshot_id
            and row.object_type == object_type
            and row.status == "active"
        ]
        return sorted(rows, key=lambda row: row.final_rank)[:limit]


class FakeSecurityRepo:
    def __init__(self) -> None:
        self.items: dict[str, SecurityRecord] = {}
        self.market_items: dict[str, SecurityRecord] = {}

    def get(self, security_id: str) -> SecurityRecord | None:
        item = self.items.get(security_id)
        return None if item is None else replace(item)

    def add(self, record: SecurityRecord) -> None:
        self.items[record.security_id] = replace(record)

    def search(self, keyword: str | None = None, *, limit: int = 100) -> list[SecurityRecord]:
        needle = (keyword or "").lower()
        rows = [
            item
            for item in self.items.values()
            if not needle
            or needle in item.security_id.lower()
            or needle in item.name.lower()
            or needle in (item.ticker or "").lower()
        ]
        return [replace(item) for item in sorted(rows, key=lambda item: item.security_id)[:limit]]

    def search_market(self, keyword: str, *, limit: int = 100) -> list[SecurityRecord]:
        needle = keyword.lower()
        rows = [
            item
            for item in self.market_items.values()
            if needle in item.security_id.lower()
            or needle in item.name.lower()
            or needle in (item.ticker or "").lower()
        ]
        return [replace(item) for item in sorted(rows, key=lambda item: item.security_id)[:limit]]

    def upsert_market(self, record: SecurityRecord) -> None:
        self.market_items[record.security_id] = replace(record)


class FakeEventRepo:
    def __init__(self) -> None:
        self.items: dict[str, EventRecord] = {}

    def get(self, event_id: str) -> EventRecord | None:
        item = self.items.get(event_id)
        return None if item is None else replace(item)

    def find_by_fingerprint(self, fingerprint: str) -> EventRecord | None:
        item = next((row for row in self.items.values() if row.fingerprint == fingerprint), None)
        return None if item is None else replace(item)

    def add(self, record: EventRecord) -> None:
        self.items[record.event_id] = replace(record)

    def update(self, record: EventRecord) -> None:
        if record.event_id not in self.items:
            raise LookupError(record.event_id)
        self.items[record.event_id] = replace(record)


class FakeThesisRepo:
    def __init__(self) -> None:
        self.theses: dict[str, ThesisRecord] = {}
        self.hypotheses: list[HypothesisRecord] = []
        self.mappings: list[MetricMappingRecord] = []

    def get(self, thesis_id: str) -> ThesisRecord | None:
        record = self.theses.get(thesis_id)
        return None if record is None else replace(record)

    def add(self, record: ThesisRecord) -> None:
        self.theses[record.thesis_id] = replace(record)

    def update(self, record: ThesisRecord) -> None:
        if record.thesis_id not in self.theses:
            raise LookupError(record.thesis_id)
        self.theses[record.thesis_id] = replace(record)

    def list_hypotheses(self, thesis_id: str) -> list[HypothesisRecord]:
        return [replace(h) for h in self.hypotheses if h.thesis_id == thesis_id]

    def get_hypothesis(self, hypothesis_id: str) -> HypothesisRecord | None:
        item = next((h for h in self.hypotheses if h.hypothesis_id == hypothesis_id), None)
        return None if item is None else replace(item)

    def add_hypothesis(self, record: HypothesisRecord) -> None:
        self.hypotheses.append(replace(record))

    def update_hypothesis(self, record: HypothesisRecord) -> None:
        for index, item in enumerate(self.hypotheses):
            if item.hypothesis_id == record.hypothesis_id:
                self.hypotheses[index] = replace(record)
                return
        raise LookupError(record.hypothesis_id)

    def list_mappings(self, hypothesis_id: str) -> list[MetricMappingRecord]:
        return [replace(m) for m in self.mappings if m.hypothesis_id == hypothesis_id]

    def add_mapping(self, record: MetricMappingRecord) -> None:
        self.mappings.append(replace(record))

    def update_mapping(self, record: MetricMappingRecord) -> None:
        for index, item in enumerate(self.mappings):
            if item.mapping_id == record.mapping_id:
                self.mappings[index] = replace(record)
                return
        raise LookupError(record.mapping_id)

    def remove_mapping(self, mapping_id: str) -> None:
        self.mappings = [item for item in self.mappings if item.mapping_id != mapping_id]

    def get_by_security(self, security_id: str) -> ThesisRecord | None:
        matching = [
            t for t in self.theses.values() if t.security_id == security_id and t.is_current
        ]
        if len(matching) > 1:
            raise ValueError(f"security {security_id} has multiple theses")
        return replace(matching[0]) if matching else None

    def get_by_securities(
        self, security_ids: tuple[str, ...], *, include_snapshots: bool = False
    ) -> dict[str, ThesisRecord]:
        return {
            security_id: replace(thesis)
            for security_id in security_ids
            if (thesis := self.get_by_security(security_id)) is not None
            and (include_snapshots or thesis.thesis_kind == "canonical")
        }

    def counts_for_theses(self, thesis_ids: tuple[str, ...]) -> dict[str, tuple[int, int]]:
        return {
            thesis_id: (
                len(hypotheses := [item for item in self.hypotheses if item.thesis_id == thesis_id]),
                sum(len(self.list_mappings(item.hypothesis_id)) for item in hypotheses),
            )
            for thesis_id in thesis_ids
        }

    def search(self, query: ThesisQuery) -> tuple[list[ThesisRecord], int]:
        """内存版分页查询。

        排序与 SQL 实现保持一致（established_on 倒序 + thesis_id 兜底），否则
        用 fake 写的分页测试通不过真实仓储。
        """
        rows = [row for row in self.theses.values() if row.is_current]
        if query.statuses:
            rows = [r for r in rows if r.status in query.statuses]
        if query.securities:
            rows = [r for r in rows if r.security_id in query.securities]
        if query.owner:
            rows = [r for r in rows if r.owner == query.owner]
        if query.keyword:
            needle = query.keyword.lower()
            rows = [r for r in rows if needle in r.title.lower() or needle in r.core_view.lower()]

        # established_on 倒序、thesis_id 正序。先按次键正排再按主键倒排会让次键
        # 方向也跟着反过来，所以这里一次排完：主键取负不可行（date 不支持），
        # 改用两段式 key 的等价写法——先按 thesis_id 正排，再稳定地按日期倒排。
        rows.sort(key=lambda r: r.thesis_id)
        rows.sort(key=lambda r: r.established_on, reverse=True)
        total = len(rows)
        window = rows[query.offset : query.offset + query.limit]
        return [replace(r) for r in window], total


class FakeEvidenceRepo:
    def __init__(self) -> None:
        self.items: dict[str, EvidenceRecord] = {}

    def get(self, evidence_id: str) -> EvidenceRecord | None:
        record = self.items.get(evidence_id)
        return None if record is None else replace(record)

    def add(self, record: EvidenceRecord) -> None:
        self.items[record.evidence_id] = replace(record)

    def update(self, record: EvidenceRecord) -> None:
        if record.evidence_id not in self.items:
            raise LookupError(record.evidence_id)
        self.items[record.evidence_id] = replace(record)

    def list_for_thesis(self, thesis_id: str) -> list[EvidenceRecord]:
        return [replace(e) for e in self.items.values() if e.thesis_id == thesis_id]


class FakeMetricRepo:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], MetricDefinitionRecord] = {
            ("MET-DEMO-001", "v1.0"): MetricDefinitionRecord(
                metric_id="MET-DEMO-001",
                version="v1.0",
                name="营业收入同比",
                unit="%",
                category="经营",
                frequency="季度",
                expected_direction=ExpectationDirection.HIGHER_BETTER,
                status="已确认",
            ),
        }

    def get(self, metric_id: str, version: str = "v1.0") -> MetricDefinitionRecord | None:
        return self.items.get((metric_id, version))

    def search(
        self, keyword: str | None = None, *, limit: int = 50
    ) -> list[MetricDefinitionRecord]:
        needle = (keyword or "").lower()
        rows = [
            item
            for item in self.items.values()
            if not needle or needle in item.metric_id.lower() or needle in item.name.lower()
        ]
        return rows[:limit]


class FakeEvidenceRelationRepo:
    """关联状态独立存放，避免测试继续误用 Evidence 的历史单关联字段。"""

    def __init__(self) -> None:
        self.items: dict[str, EvidenceRelationRecord] = {}

    def get(self, relation_id: str) -> EvidenceRelationRecord | None:
        item = self.items.get(relation_id)
        return replace(item) if item else None

    def list_for_evidence(self, evidence_id: str) -> list[EvidenceRelationRecord]:
        return [replace(item) for item in self.items.values() if item.evidence_id == evidence_id]

    def list_for_thesis(self, thesis_id: str) -> list[EvidenceRelationRecord]:
        return [replace(item) for item in self.items.values() if item.thesis_id == thesis_id]

    def add(self, record: EvidenceRelationRecord) -> None:
        self.items[record.relation_id] = replace(record)

    def update(self, record: EvidenceRelationRecord) -> None:
        if record.relation_id not in self.items:
            raise LookupError(record.relation_id)
        self.items[record.relation_id] = replace(record)


class FakeEvidenceFeedRepo:
    def __init__(self) -> None:
        self.items: list[EvidenceFeedRecord] = []

    def search(self, *, thesis_ids, statuses=(), direction=None, priorities=(), limit=20, offset=0):
        rows = [item for item in self.items if item.thesis_id in thesis_ids]
        if statuses:
            rows = [item for item in rows if item.confirmation_status in statuses]
        if direction is not None:
            rows = [item for item in rows if item.direction is direction]
        if priorities:
            rows = [item for item in rows if item.priority in priorities]
        rank = {"high": 0, "medium": 1, "low": 2}
        rows.sort(
            key=lambda item: (
                rank[item.priority],
                -(item.disclosed_at.timestamp() if item.disclosed_at else 0),
            )
        )
        return [replace(item) for item in rows[offset : offset + limit]], len(rows)


class FakeObservationRepo:
    def __init__(self) -> None:
        self.items: list[ObservationRecord] = []

    def list_for_security(self, security_id: str) -> list[ObservationRecord]:
        return [replace(o) for o in self.items if o.security_id == security_id]

    def list_for_metric(self, security_id: str, metric_id: str) -> list[ObservationRecord]:
        return [
            replace(o)
            for o in self.items
            if o.security_id == security_id and o.metric_id == metric_id
        ]

    def existing_keys(self, security_id: str, data_version: str) -> set[tuple[str, str]]:
        return {
            (item.metric_id, item.period)
            for item in self.items
            if item.security_id == security_id and item.data_version == data_version
        }

    def add(self, record: ObservationRecord) -> None:
        self.items.append(replace(record))

    def add_if_absent(self, record: ObservationRecord) -> bool:
        if any(
            item.security_id == record.security_id
            and item.metric_id == record.metric_id
            and item.metric_version == record.metric_version
            and item.period == record.period
            and item.data_version == record.data_version
            for item in self.items
        ):
            return False
        self.items.append(replace(record))
        return True

    def add_many_if_absent(self, records: list[ObservationRecord]) -> int:
        return sum(self.add_if_absent(record) for record in records)


class FakeSuggestionRepo:
    def __init__(self) -> None:
        self.items: dict[int, SuggestionRecord] = {}
        self._next = 1

    def add(self, record: SuggestionRecord) -> SuggestionRecord:
        record.suggestion_id = self._next
        self._next += 1
        self.items[record.suggestion_id] = replace(record)
        return record

    def get(self, suggestion_id: int) -> SuggestionRecord | None:
        record = self.items.get(suggestion_id)
        return None if record is None else replace(record)

    def update(self, record: SuggestionRecord) -> None:
        if record.suggestion_id is None or record.suggestion_id not in self.items:
            raise LookupError(record.suggestion_id)
        self.items[record.suggestion_id] = replace(record)

    def list_for_thesis(self, thesis_id: str) -> list[SuggestionRecord]:
        return [
            replace(s)
            for s in sorted(self.items.values(), key=lambda x: x.suggestion_id or 0)
            if s.thesis_id == thesis_id
        ]


class FakeVersionRepo:
    """版本仓储。不提供 update：历史快照禁止修改（PRD 5.3）。"""

    def __init__(self) -> None:
        self.items: list[VersionRecord] = []

    def add(self, record: VersionRecord) -> None:
        self.items.append(replace(record))

    def latest(self, thesis_id: str) -> VersionRecord | None:
        matching = [v for v in self.items if v.thesis_id == thesis_id]
        return replace(max(matching, key=lambda v: v.version)) if matching else None

    def list_for_thesis(self, thesis_id: str) -> list[VersionRecord]:
        return [replace(v) for v in self.items if v.thesis_id == thesis_id]


class FakeAuditRepo:
    def __init__(self) -> None:
        self.items: list[AuditRecord] = []

    def add(self, record: AuditRecord) -> None:
        self.items.append(record)

    def list_for_object(self, object_type: str, object_id: str) -> list[AuditRecord]:
        return [r for r in self.items if r.object_type == object_type and r.object_id == object_id]

    def page_for_object(
        self, object_type: str, object_id: str, *, limit: int, offset: int
    ) -> tuple[list[AuditRecord], int]:
        """倒序分页，与 SQL 实现一致。"""
        matched = list(reversed(self.list_for_object(object_type, object_id)))
        return matched[offset : offset + limit], len(matched)

    def actions(self) -> list[str]:
        return [r.action for r in self.items]


class ExplodingAuditRepo(FakeAuditRepo):
    """写审计就抛错。用于验证审计失败会让业务动作回滚。"""

    def add(self, record: AuditRecord) -> None:
        raise RuntimeError("审计写入失败")


class FakeReviewTaskRepo:
    def __init__(self) -> None:
        self.items: dict[str, ReviewTaskRecord] = {}

    def add(self, record: ReviewTaskRecord) -> ReviewTaskRecord:
        self.items[record.task_id] = replace(record)
        return replace(record)

    def get(self, task_id: str) -> ReviewTaskRecord | None:
        record = self.items.get(task_id)
        return None if record is None else replace(record)

    def update(self, record: ReviewTaskRecord) -> None:
        if record.task_id not in self.items:
            raise LookupError(record.task_id)
        self.items[record.task_id] = replace(record)

    def list_for_assignee(
        self, assignee: str, *, state: str | None = None, limit: int = 100
    ) -> list[ReviewTaskRecord]:
        matching = [
            replace(record)
            for record in self.items.values()
            if record.assignee == assignee and (state is None or record.state == state)
        ]
        return matching[:limit]


class FakeDocumentProcessingJobRepo:
    def __init__(self) -> None:
        self.items: dict[str, DocumentProcessingJobRecord] = {}

    def add(self, record: DocumentProcessingJobRecord) -> None:
        self.items[record.job_id] = replace(record)

    def get(self, job_id: str) -> DocumentProcessingJobRecord | None:
        row = self.items.get(job_id)
        return None if row is None else replace(row)

    def get_by_document(self, document_id: str) -> DocumentProcessingJobRecord | None:
        rows = [row for row in self.items.values() if row.document_id == document_id]
        return replace(rows[-1]) if rows else None

    def update(self, record: DocumentProcessingJobRecord) -> None:
        if record.job_id not in self.items:
            raise LookupError(record.job_id)
        self.items[record.job_id] = replace(record)

    def list_for_owner(self, owner: str, *, status: str | None = None, limit: int = 100):
        rows = [
            replace(row)
            for row in reversed(list(self.items.values()))
            if row.owner == owner and (status is None or row.status == status)
        ]
        return rows[:limit]

    def list_stale(self, *, before, statuses: tuple[str, ...]):
        return [
            replace(row)
            for row in self.items.values()
            if row.status in statuses
            and (row.updated_at or row.created_at) is not None
            and (row.updated_at or row.created_at) < before  # type: ignore[operator]
        ]


class FakeIngestionReviewRepo:
    def __init__(self) -> None:
        self.items: dict[str, IngestionReviewRecord] = {}

    def add(self, record: IngestionReviewRecord) -> IngestionReviewRecord:
        self.items[record.review_id] = replace(record)
        return replace(record)

    def get(self, review_id: str) -> IngestionReviewRecord | None:
        row = self.items.get(review_id)
        return None if row is None else replace(row)

    def get_by_dedupe_key(self, dedupe_key: str) -> IngestionReviewRecord | None:
        row = next((x for x in self.items.values() if x.dedupe_key == dedupe_key), None)
        return None if row is None else replace(row)

    def update(self, record: IngestionReviewRecord) -> None:
        if record.review_id not in self.items:
            raise LookupError(record.review_id)
        self.items[record.review_id] = replace(record)

    def list_for_assignee(self, assignee: str, *, status: str | None = None, limit: int = 100):
        rows = [
            replace(row)
            for row in self.items.values()
            if row.assignee == assignee and (status is None or row.status == status)
        ]
        return rows[:limit]


class FakeDocumentRepo:
    def __init__(self) -> None:
        self.items: dict[str, DocumentRecord] = {}
        self.segments: dict[str, list[DocumentSegmentRecord]] = {}
        self.facts: dict[str, list[DocumentFactRecord]] = {}

    def get(self, document_id: str) -> DocumentRecord | None:
        record = self.items.get(document_id)
        return None if record is None else replace(record)

    def list_for_security(self, security_id: str, *, limit: int = 100) -> list[DocumentRecord]:
        rows = [replace(record) for record in self.items.values() if record.security_id == security_id]
        rows.sort(key=lambda record: record.published_at, reverse=True)
        return rows[:limit]

    def find_by_content_hash(self, content_hash: str, parser_version: str) -> DocumentRecord | None:
        for record in self.items.values():
            if record.content_hash == content_hash and record.parser_version == parser_version:
                return replace(record)
        return None

    def add(self, record, segments, facts) -> None:
        self.items[record.document_id] = replace(record)
        self.segments[record.document_id] = list(segments)
        self.facts[record.document_id] = list(facts)

    def list_segments(self, document_id: str) -> list[DocumentSegmentRecord]:
        return list(self.segments.get(document_id, []))

    def list_facts(self, document_id: str) -> list[DocumentFactRecord]:
        return list(self.facts.get(document_id, []))

    def update_security(self, document_id: str, security_id: str) -> None:
        record = self.items.get(document_id)
        if record is None:
            raise LookupError(document_id)
        self.items[document_id] = replace(record, security_id=security_id)

    def update_visibility(self, document_id: str, visibility_label: str) -> None:
        record = self.items.get(document_id)
        if record is None:
            raise LookupError(document_id)
        self.items[document_id] = replace(record, visibility_label=visibility_label)

    def mark_deleted(self, document_id: str, deleted_at: datetime) -> None:
        record = self.items.get(document_id)
        if record is None:
            raise LookupError(document_id)
        self.items[document_id] = replace(record, visibility_label="已删除", deleted_at=deleted_at)


class FakeAdjudicationDecisionRepo:
    def __init__(self) -> None:
        self.items: dict[str, AdjudicationDecisionRecord] = {}

    def get(self, event_id: str) -> AdjudicationDecisionRecord | None:
        item = self.items.get(event_id)
        return None if item is None else replace(item)

    def add(self, record: AdjudicationDecisionRecord) -> AdjudicationDecisionRecord:
        self.items[record.event_id] = replace(record)
        return replace(record)


def build_fake_uow(*, audit: FakeAuditRepo | None = None) -> UnitOfWork:
    return UnitOfWork(
        securities=FakeSecurityRepo(),
        events=FakeEventRepo(),
        thesis=FakeThesisRepo(),
        metrics=FakeMetricRepo(),
        evidence=FakeEvidenceRepo(),
        relations=FakeEvidenceRelationRepo(),
        feed=FakeEvidenceFeedRepo(),
        observations=FakeObservationRepo(),
        suggestions=FakeSuggestionRepo(),
        versions=FakeVersionRepo(),
        audit=audit or FakeAuditRepo(),
        reviews=FakeReviewTaskRepo(),
        processing_jobs=FakeDocumentProcessingJobRepo(),
        ingestion_reviews=FakeIngestionReviewRepo(),
        documents=FakeDocumentRepo(),
        adjudications=FakeAdjudicationDecisionRepo(),
        assets=FakeAssetRepo(),
        ranking=FakeRankingPriorRepo(),
    )
