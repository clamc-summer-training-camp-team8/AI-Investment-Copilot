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
    HypothesisRecord,
    MetricMappingRecord,
    ObservationRecord,
    SuggestionRecord,
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

    def actions(self) -> list[str]:
        return [r.action for r in self.items]


class ExplodingAuditRepo(FakeAuditRepo):
    """写审计就抛错。用于验证审计失败会让业务动作回滚。"""

    def add(self, record: AuditRecord) -> None:
        raise RuntimeError("审计写入失败")


def build_fake_uow(*, audit: FakeAuditRepo | None = None) -> UnitOfWork:
    return UnitOfWork(
        thesis=FakeThesisRepo(),
        evidence=FakeEvidenceRepo(),
        observations=FakeObservationRepo(),
        suggestions=FakeSuggestionRepo(),
        versions=FakeVersionRepo(),
        audit=audit or FakeAuditRepo(),
    )
