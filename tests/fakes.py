"""内存假仓储。

编排逻辑（状态流转、人工闸门、版本触发、权限判断）不该为了测试而必须起数据库。
真实 SQLAlchemy 仓储由 tests/integration 覆盖。

这些实现刻意保持"笨"：不加缓存、不做排序优化。假仓储一旦有自己的逻辑，测试就
可能通过假仓储的 bug 而不是被测代码的正确性。
"""

from __future__ import annotations

from dataclasses import replace

from app.core.domain import (
    AuditRecord,
    EvidenceRecord,
    EvidenceFeedRecord,
    EvidenceRelationRecord,
    HypothesisRecord,
    MetricMappingRecord,
    ObservationRecord,
    ReviewTaskRecord,
    SuggestionRecord,
    ThesisQuery,
    ThesisRecord,
    UnitOfWork,
    VersionRecord,
)


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

    def add_hypothesis(self, record: HypothesisRecord) -> None:
        self.hypotheses.append(replace(record))

    def list_mappings(self, hypothesis_id: str) -> list[MetricMappingRecord]:
        return [replace(m) for m in self.mappings if m.hypothesis_id == hypothesis_id]

    def add_mapping(self, record: MetricMappingRecord) -> None:
        self.mappings.append(replace(record))

    def find_by_security(self, security_id: str) -> list[ThesisRecord]:
        return [replace(t) for t in self.theses.values() if t.security_id == security_id]

    def search(self, query: ThesisQuery) -> tuple[list[ThesisRecord], int]:
        """内存版分页查询。

        排序与 SQL 实现保持一致（established_on 倒序 + thesis_id 兜底），否则
        用 fake 写的分页测试通不过真实仓储。
        """
        rows = list(self.theses.values())
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
        rows.sort(key=lambda item: (rank[item.priority], -(item.disclosed_at.timestamp() if item.disclosed_at else 0)))
        return [replace(item) for item in rows[offset : offset + limit]], len(rows)


class FakeObservationRepo:
    def __init__(self) -> None:
        self.items: list[ObservationRecord] = []

    def list_for_metric(self, security_id: str, metric_id: str) -> list[ObservationRecord]:
        return [
            replace(o)
            for o in self.items
            if o.security_id == security_id and o.metric_id == metric_id
        ]

    def add(self, record: ObservationRecord) -> None:
        self.items.append(replace(record))


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


def build_fake_uow(*, audit: FakeAuditRepo | None = None) -> UnitOfWork:
    return UnitOfWork(
        thesis=FakeThesisRepo(),
        evidence=FakeEvidenceRepo(),
        relations=FakeEvidenceRelationRepo(),
        feed=FakeEvidenceFeedRepo(),
        observations=FakeObservationRepo(),
        suggestions=FakeSuggestionRepo(),
        versions=FakeVersionRepo(),
        audit=audit or FakeAuditRepo(),
        reviews=FakeReviewTaskRepo(),
    )
