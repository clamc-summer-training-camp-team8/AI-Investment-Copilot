"""证据、观测值、状态建议、版本、审计仓储。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.domain import (
    AuditRecord,
    EvidenceRecord,
    ObservationRecord,
    SuggestionRecord,
    VersionRecord,
)
from app.core.enums import (
    ConfirmationStatus,
    ImpactDirection,
    ReviewStatus,
    ThesisStatus,
)
from app.db.models.core import Document, Evidence, MetricObservation
from app.db.models.governance import AuditLog, StatusSuggestionLog, ThesisVersion


def _to_evidence(row: Evidence, *, label: str = "内部") -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=row.evidence_id,
        thesis_id=row.thesis_id,
        hypothesis_id=row.hypothesis_id,
        evidence_type=row.evidence_type,
        direction=ImpactDirection(row.direction),
        evidence_locator=row.evidence_locator,
        event_id=row.event_id,
        strength=row.strength,
        strength_score=row.strength_score,
        horizon=row.horizon,
        ai_status=row.ai_status,
        ai_confidence=row.ai_confidence,
        model_version=row.model_version,
        prompt_version=row.prompt_version,
        confirmation_status=ConfirmationStatus(row.confirmation_status),
        review_status=ReviewStatus(row.review_status)
        if row.review_status
        else ReviewStatus.PENDING,
        confirmed_by=row.confirmed_by,
        confirmed_at=row.confirmed_at,
        review_note=row.review_note,
        source_visibility_label=label,
    )


class SqlEvidenceRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, evidence_id: str) -> EvidenceRecord | None:
        row = self._session.get(Evidence, evidence_id)
        if row is None:
            return None
        return _to_evidence(row, label=self._document_label(row.evidence_locator))

    def add(self, record: EvidenceRecord) -> None:
        self._session.add(
            Evidence(
                evidence_id=record.evidence_id,
                event_id=record.event_id,
                thesis_id=record.thesis_id,
                hypothesis_id=record.hypothesis_id,
                evidence_type=record.evidence_type,
                direction=record.direction.value,
                strength=record.strength,
                strength_score=record.strength_score,
                horizon=record.horizon,
                evidence_locator=record.evidence_locator,
                ai_status=record.ai_status,
                ai_confidence=record.ai_confidence,
                model_version=record.model_version,
                prompt_version=record.prompt_version,
                confirmation_status=record.confirmation_status.value,
                review_status=record.review_status.value,
                review_note=record.review_note,
                confirmed_by=record.confirmed_by,
                confirmed_at=record.confirmed_at,
            )
        )
        self._session.flush()

    def update(self, record: EvidenceRecord) -> None:
        row = self._session.get(Evidence, record.evidence_id)
        if row is None:
            raise LookupError(f"evidence {record.evidence_id} 不存在")
        row.hypothesis_id = record.hypothesis_id
        row.direction = record.direction.value
        row.confirmation_status = record.confirmation_status.value
        row.review_status = record.review_status.value
        row.review_note = record.review_note
        row.confirmed_by = record.confirmed_by
        row.confirmed_at = record.confirmed_at
        self._session.flush()

    def list_for_thesis(self, thesis_id: str) -> list[EvidenceRecord]:
        rows = self._session.scalars(
            select(Evidence).where(Evidence.thesis_id == thesis_id).order_by(Evidence.evidence_id)
        ).all()
        return [_to_evidence(r, label=self._document_label(r.evidence_locator)) for r in rows]

    def _document_label(self, locator: str) -> str:
        """取来源文档的权限标签，供「证据可见性不得高于来源文档」校验使用。

        取不到时返回最严格的标签，而不是最宽松的：定位不到来源就当敏感处理，
        宁可拦住一次合法确认，也不要放过一次越权。
        """
        document_id = locator.split("#", 1)[0]
        label = self._session.scalars(
            select(Document.visibility_label).where(Document.document_id == document_id)
        ).first()
        return label or "机密"


class SqlObservationRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_metric(self, security_id: str, metric_id: str) -> list[ObservationRecord]:
        rows = self._session.scalars(
            select(MetricObservation)
            .where(
                MetricObservation.security_id == security_id,
                MetricObservation.metric_id == metric_id,
            )
            .order_by(MetricObservation.observation_date)
        ).all()
        return [
            ObservationRecord(
                security_id=r.security_id,
                metric_id=r.metric_id,
                period=r.period,
                observation_date=r.observation_date,
                unit=r.unit,
                actual_value=r.actual_value,
                expected_value=r.expected_value,
                benchmark_value=r.benchmark_value,
                metric_version=r.metric_version,
                period_type=r.period_type,
                source_document_id=r.source_document_id,
                data_version=r.data_version,
            )
            for r in rows
        ]

    def add(self, record: ObservationRecord) -> None:
        self._session.add(
            MetricObservation(
                security_id=record.security_id,
                metric_id=record.metric_id,
                metric_version=record.metric_version,
                period=record.period,
                period_type=record.period_type,
                observation_date=record.observation_date,
                actual_value=record.actual_value,
                unit=record.unit,
                expected_value=record.expected_value,
                benchmark_value=record.benchmark_value,
                source_document_id=record.source_document_id,
                data_version=record.data_version,
            )
        )
        self._session.flush()


class SqlSuggestionRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, record: SuggestionRecord) -> SuggestionRecord:
        row = StatusSuggestionLog(
            thesis_id=record.thesis_id,
            current_status=record.current_status.value,
            suggested_status=record.suggested_status.value,
            reasons=list(record.reasons),
            triggered_hypotheses=list(record.triggered_hypotheses),
            rule_version=record.rule_version,
        )
        self._session.add(row)
        self._session.flush()
        record.suggestion_id = row.id
        return record

    def get(self, suggestion_id: int) -> SuggestionRecord | None:
        row = self._session.get(StatusSuggestionLog, suggestion_id)
        if row is None:
            return None
        return SuggestionRecord(
            thesis_id=row.thesis_id,
            current_status=ThesisStatus(row.current_status),
            suggested_status=ThesisStatus(row.suggested_status),
            reasons=list(row.reasons or []),
            rule_version=row.rule_version,
            triggered_hypotheses=list(row.triggered_hypotheses or []),
            human_action=row.human_action,
            human_reason=row.human_reason,
            acted_by=row.acted_by,
            acted_at=row.acted_at,
            suggestion_id=row.id,
        )

    def update(self, record: SuggestionRecord) -> None:
        if record.suggestion_id is None:
            raise ValueError("状态建议缺少主键，无法更新")
        row = self._session.get(StatusSuggestionLog, record.suggestion_id)
        if row is None:
            raise LookupError(f"status_suggestion_log {record.suggestion_id} 不存在")
        row.human_action = record.human_action
        row.human_reason = record.human_reason
        row.acted_by = record.acted_by
        row.acted_at = record.acted_at
        self._session.flush()

    def list_for_thesis(self, thesis_id: str) -> list[SuggestionRecord]:
        rows = self._session.scalars(
            select(StatusSuggestionLog)
            .where(StatusSuggestionLog.thesis_id == thesis_id)
            .order_by(StatusSuggestionLog.id)
        ).all()
        result: list[SuggestionRecord] = []
        for row in rows:
            item = self.get(row.id)
            if item is not None:
                result.append(item)
        return result


class SqlVersionRepo:
    """版本仓储。

    刻意不提供 update：历史版本冻结当时可得信息，禁止用未来信息覆盖历史记录
    （PRD 5.3）。发现快照有误的正确做法是生成新版本并说明原因。
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, record: VersionRecord) -> None:
        self._session.add(
            ThesisVersion(
                thesis_id=record.thesis_id,
                version=record.version,
                snapshot=record.snapshot,
                changed_fields=list(record.changed_fields),
                change_reason=record.change_reason,
                triggered_by=record.triggered_by,
                created_by=record.created_by,
            )
        )
        self._session.flush()

    def latest(self, thesis_id: str) -> VersionRecord | None:
        row = self._session.scalars(
            select(ThesisVersion)
            .where(ThesisVersion.thesis_id == thesis_id)
            .order_by(ThesisVersion.version.desc())
            .limit(1)
        ).first()
        return None if row is None else _to_version(row)

    def list_for_thesis(self, thesis_id: str) -> list[VersionRecord]:
        rows = self._session.scalars(
            select(ThesisVersion)
            .where(ThesisVersion.thesis_id == thesis_id)
            .order_by(ThesisVersion.version)
        ).all()
        return [_to_version(r) for r in rows]


def _to_version(row: ThesisVersion) -> VersionRecord:
    return VersionRecord(
        thesis_id=row.thesis_id,
        version=row.version,
        snapshot=dict(row.snapshot or {}),
        triggered_by=row.triggered_by,
        created_by=row.created_by,
        change_reason=row.change_reason,
        changed_fields=list(row.changed_fields or []),
    )


class SqlAuditRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, record: AuditRecord) -> None:
        self._session.add(
            AuditLog(
                actor=record.actor,
                action=record.action,
                object_type=record.object_type,
                object_id=record.object_id,
                detail=record.detail,
                model_version=record.model_version,
            )
        )
        self._session.flush()

    def list_for_object(self, object_type: str, object_id: str) -> list[AuditRecord]:
        rows = self._session.scalars(
            select(AuditLog)
            .where(AuditLog.object_type == object_type, AuditLog.object_id == object_id)
            .order_by(AuditLog.id)
        ).all()
        return [
            AuditRecord(
                actor=r.actor,
                action=r.action,
                object_type=r.object_type,
                object_id=r.object_id,
                detail=dict(r.detail) if r.detail else None,
                model_version=r.model_version,
            )
            for r in rows
        ]
