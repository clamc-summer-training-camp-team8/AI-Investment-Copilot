"""证据、观测值、状态建议、版本、审计仓储。"""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.domain import (
    AuditRecord,
    EvidenceFeedRecord,
    EvidenceRecord,
    EvidenceRelationRecord,
    ObservationRecord,
    SuggestionRecord,
    VersionRecord,
)
from app.core.enums import (
    ConfirmationStatus,
    ImpactDirection,
    Importance,
    ReviewStatus,
    ThesisStatus,
)
from app.db.models.core import (
    Document,
    Evidence,
    EvidenceRelation,
    Hypothesis,
    MetricObservation,
    Security,
    Thesis,
)
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
        security_id=row.security_id,
        fact_excerpt=row.fact_excerpt,
        source_document_id=row.source_document_id,
        source_document_title=row.source_document_title,
        disclosed_at=row.disclosed_at,
        occurred_at=row.occurred_at,
        source_url=row.source_url,
        retrieval_trace=dict(row.retrieval_trace) if row.retrieval_trace else None,
        ingested_at=row.created_at,
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
                security_id=record.security_id,
                event_id=record.event_id,
                thesis_id=record.thesis_id,
                hypothesis_id=record.hypothesis_id,
                evidence_type=record.evidence_type,
                direction=record.direction.value,
                strength=record.strength,
                strength_score=record.strength_score,
                horizon=record.horizon,
                evidence_locator=record.evidence_locator,
                fact_excerpt=record.fact_excerpt,
                source_document_id=record.source_document_id,
                source_document_title=record.source_document_title,
                disclosed_at=record.disclosed_at,
                occurred_at=record.occurred_at,
                source_url=record.source_url,
                ai_status=record.ai_status,
                ai_confidence=record.ai_confidence,
                model_version=record.model_version,
                prompt_version=record.prompt_version,
                retrieval_trace=record.retrieval_trace,
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
        # 关联表是当前关系的唯一事实来源。一个证据可关联多个逻辑，
        # 因而不能继续只按 Evidence.thesis_id 读取，否则新增关联不会出现在目标逻辑中。
        relation_rows = self._session.execute(
            select(Evidence, EvidenceRelation)
            .join(EvidenceRelation, EvidenceRelation.evidence_id == Evidence.evidence_id)
            .where(
                EvidenceRelation.thesis_id == thesis_id,
                EvidenceRelation.status != ConfirmationStatus.DEACTIVATED.value,
            )
            .order_by(Evidence.evidence_id, EvidenceRelation.created_at)
        ).all()
        if relation_rows:
            return [
                replace(
                    _to_evidence(evidence, label=self._document_label(evidence.evidence_locator)),
                    thesis_id=relation.thesis_id,
                    hypothesis_id=relation.hypothesis_id,
                    direction=ImpactDirection(relation.direction),
                    strength=relation.strength,
                    confirmation_status=ConfirmationStatus(relation.status),
                    review_note=relation.reason,
                    confirmed_by=relation.reviewed_by,
                    confirmed_at=relation.reviewed_at,
                )
                for evidence, relation in relation_rows
            ]

        # 尚未执行 0003 迁移的旧库保留原字段读取，确保平滑升级。
        rows = self._session.scalars(
            select(Evidence).where(Evidence.thesis_id == thesis_id).order_by(Evidence.evidence_id)
        ).all()
        return [_to_evidence(row, label=self._document_label(row.evidence_locator)) for row in rows]

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


def _to_relation(row: EvidenceRelation) -> EvidenceRelationRecord:
    return EvidenceRelationRecord(
        relation_id=row.relation_id,
        evidence_id=row.evidence_id,
        thesis_id=row.thesis_id,
        hypothesis_id=row.hypothesis_id,
        direction=ImpactDirection(row.direction),
        strength=row.strength,
        status=ConfirmationStatus(row.status),
        created_by=row.created_by,
        reason=row.reason,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        deactivated_by=row.deactivated_by,
        deactivated_at=row.deactivated_at,
    )


class SqlEvidenceRelationRepo:
    """证据关联仓储。旧 Evidence 上的关联字段仅保留给兼容接口读取。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, relation_id: str) -> EvidenceRelationRecord | None:
        row = self._session.get(EvidenceRelation, relation_id)
        return _to_relation(row) if row else None

    def list_for_evidence(self, evidence_id: str) -> list[EvidenceRelationRecord]:
        rows = self._session.scalars(
            select(EvidenceRelation)
            .where(EvidenceRelation.evidence_id == evidence_id)
            .order_by(EvidenceRelation.created_at.desc())
        ).all()
        return [_to_relation(row) for row in rows]

    def list_for_thesis(self, thesis_id: str) -> list[EvidenceRelationRecord]:
        rows = self._session.scalars(
            select(EvidenceRelation).where(EvidenceRelation.thesis_id == thesis_id)
        ).all()
        return [_to_relation(row) for row in rows]

    def add(self, record: EvidenceRelationRecord) -> None:
        self._session.add(
            EvidenceRelation(
                relation_id=record.relation_id,
                evidence_id=record.evidence_id,
                thesis_id=record.thesis_id,
                hypothesis_id=record.hypothesis_id,
                direction=record.direction.value,
                strength=record.strength,
                reason=record.reason,
                status=record.status.value,
                created_by=record.created_by,
                reviewed_by=record.reviewed_by,
                reviewed_at=record.reviewed_at,
                deactivated_by=record.deactivated_by,
                deactivated_at=record.deactivated_at,
            )
        )
        self._session.flush()

    def update(self, record: EvidenceRelationRecord) -> None:
        row = self._session.get(EvidenceRelation, record.relation_id)
        if row is None:
            raise LookupError(f"relation {record.relation_id} 不存在")
        row.hypothesis_id = record.hypothesis_id
        row.direction = record.direction.value
        row.strength = record.strength
        row.reason = record.reason
        row.status = record.status.value
        row.reviewed_by = record.reviewed_by
        row.reviewed_at = record.reviewed_at
        row.deactivated_by = record.deactivated_by
        row.deactivated_at = record.deactivated_at
        self._session.flush()


class SqlEvidenceFeedRepo:
    """服务端聚合可读证据列表，避免前端按证据逐条补查标题和假设。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def search(
        self,
        *,
        thesis_ids: tuple[str, ...],
        statuses: tuple[ConfirmationStatus, ...] = (),
        direction: ImpactDirection | None = None,
        priorities: tuple[str, ...] = (),
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[EvidenceFeedRecord], int]:
        if not thesis_ids:
            return [], 0

        conditions = [
            EvidenceRelation.thesis_id.in_(thesis_ids),
            EvidenceRelation.status != ConfirmationStatus.DEACTIVATED.value,
        ]
        if statuses:
            conditions.append(EvidenceRelation.status.in_([item.value for item in statuses]))
        if direction is not None:
            conditions.append(EvidenceRelation.direction == direction.value)

        priority_rank = case(
            (
                (EvidenceRelation.direction == ImpactDirection.CONFLICT.value)
                & (EvidenceRelation.strength == "高"),
                0,
            ),
            (Thesis.status == ThesisStatus.MAJOR_RISK.value, 0),
            (
                (EvidenceRelation.status == ConfirmationStatus.PENDING.value)
                & (Hypothesis.importance == "核心"),
                1,
            ),
            else_=2,
        ).label("priority_rank")
        if priorities:
            ranks = {"high": 0, "medium": 1, "low": 2}
            conditions.append(priority_rank.in_([ranks[item] for item in priorities]))

        base = (
            select(Evidence, EvidenceRelation, Thesis, Hypothesis, Security, priority_rank)
            .join(EvidenceRelation, EvidenceRelation.evidence_id == Evidence.evidence_id)
            .join(Thesis, Thesis.thesis_id == EvidenceRelation.thesis_id)
            .join(Hypothesis, Hypothesis.hypothesis_id == EvidenceRelation.hypothesis_id)
            .join(Security, Security.security_id == Evidence.security_id)
            .where(*conditions)
        )
        total = (
            self._session.scalar(select(func.count()).select_from(base.order_by(None).subquery()))
            or 0
        )
        rows = self._session.execute(
            base.order_by(priority_rank, Evidence.disclosed_at.desc(), Evidence.evidence_id)
            .limit(limit)
            .offset(offset)
        ).all()
        priority_labels = {0: "high", 1: "medium", 2: "low"}
        return [
            EvidenceFeedRecord(
                evidence_id=evidence.evidence_id,
                relation_id=relation.relation_id,
                security_id=security.security_id,
                security_name=security.name,
                thesis_id=thesis.thesis_id,
                thesis_title=thesis.title,
                thesis_owner=thesis.owner,
                thesis_status=ThesisStatus(thesis.status),
                thesis_established_on=thesis.established_on,
                thesis_horizon_end_on=thesis.horizon_end_on,
                hypothesis_id=hypothesis.hypothesis_id,
                hypothesis_statement=hypothesis.statement,
                hypothesis_importance=Importance(hypothesis.importance),
                source_document_id=evidence.source_document_id,
                source_document_title=evidence.source_document_title,
                fact_excerpt=evidence.fact_excerpt,
                disclosed_at=evidence.disclosed_at,
                occurred_at=evidence.occurred_at,
                source_url=evidence.source_url,
                direction=ImpactDirection(relation.direction),
                strength=relation.strength,
                ai_confidence=evidence.ai_confidence,
                confirmation_status=ConfirmationStatus(relation.status),
                priority=priority_labels[int(rank)],
            )
            for evidence, relation, thesis, hypothesis, security, rank in rows
        ], int(total)


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
                ingested_at=r.ingested_at,
            )
            for r in rows
        ]

    def add(self, record: ObservationRecord) -> None:
        row = MetricObservation(
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
        if record.ingested_at is not None:
            row.ingested_at = record.ingested_at
        self._session.add(row)
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
                data_cutoff_at=record.data_cutoff_at,
                rule_version=record.rule_version,
                model_versions=record.model_versions or None,
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
        data_cutoff_at=row.data_cutoff_at,
        rule_version=row.rule_version,
        model_versions=list(row.model_versions or []),
        created_at=row.created_at,
    )


def _to_audit(row: AuditLog) -> AuditRecord:
    return AuditRecord(
        actor=row.actor,
        action=row.action,
        object_type=row.object_type,
        object_id=row.object_id,
        detail=dict(row.detail) if row.detail else None,
        model_version=row.model_version,
        occurred_at=row.occurred_at,
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

    def page_for_object(
        self, object_type: str, object_id: str, *, limit: int, offset: int
    ) -> tuple[list[AuditRecord], int]:
        """分页版留痕查询。倒序：留痕页最关心最近发生了什么。"""
        conditions = (AuditLog.object_type == object_type, AuditLog.object_id == object_id)
        total = self._session.scalar(select(func.count()).select_from(AuditLog).where(*conditions))
        rows = self._session.scalars(
            select(AuditLog)
            .where(*conditions)
            .order_by(AuditLog.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return [_to_audit(r) for r in rows], int(total or 0)

    def list_for_object(self, object_type: str, object_id: str) -> list[AuditRecord]:
        rows = self._session.scalars(
            select(AuditLog)
            .where(AuditLog.object_type == object_type, AuditLog.object_id == object_id)
            .order_by(AuditLog.id)
        ).all()
        return [_to_audit(r) for r in rows]
