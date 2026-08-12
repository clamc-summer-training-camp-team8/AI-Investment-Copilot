"""版本、状态建议与审计模型。

PRD 5.3：历史版本冻结当时可得信息，禁止使用未来信息覆盖历史记录。
PRD 5.4：系统可提出状态建议，正式状态变更必须由负责人确认并填写原因。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, updated_at_column


class ThesisVersion(Base):
    """冻结的逻辑版本快照。发布产生 V1，核心字段正式修改产生新版本。"""

    __tablename__ = "thesis_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thesis_id: Mapped[str] = mapped_column(
        ForeignKey("thesis.thesis_id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, comment="卡片全字段快照，冻结当时可得信息"
    )
    changed_fields: Mapped[list | None] = mapped_column(JSONB)
    change_reason: Mapped[str | None] = mapped_column(Text)
    triggered_by: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="发布/字段修改/证据确认/状态变更/复核"
    )

    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    data_cutoff_at: Mapped[datetime | None] = mapped_column()
    rule_version: Mapped[str | None] = mapped_column(String(32))
    model_versions: Mapped[list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (UniqueConstraint("thesis_id", "version"),)


class StatusSuggestionLog(Base):
    """状态建议记录。建议本身不改变状态，人工处置结果单独留痕。"""

    __tablename__ = "status_suggestion_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thesis_id: Mapped[str] = mapped_column(
        ForeignKey("thesis.thesis_id", ondelete="CASCADE"), nullable=False
    )

    current_status: Mapped[str] = mapped_column(String(16), nullable=False)
    suggested_status: Mapped[str] = mapped_column(String(16), nullable=False)
    reasons: Mapped[list] = mapped_column(JSONB, nullable=False)
    triggered_hypotheses: Mapped[list | None] = mapped_column(JSONB)
    rule_version: Mapped[str] = mapped_column(String(32), nullable=False)

    human_action: Mapped[str | None] = mapped_column(
        String(16), comment="接受/拒绝/修改；未处置为空"
    )
    human_reason: Mapped[str | None] = mapped_column(Text)
    acted_by: Mapped[str | None] = mapped_column(String(64))
    acted_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (Index("ix_status_suggestion_thesis", "thesis_id"),)


class ReviewTask(Base):
    """复核任务。到期、重大事件或失效条件触发创建。"""

    __tablename__ = "review_task"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thesis_id: Mapped[str] = mapped_column(
        ForeignKey("thesis.thesis_id", ondelete="CASCADE"), nullable=False
    )
    trigger: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="到期/重大事件/失效条件/人工发起"
    )
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="普通")
    assignee: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="待处理")
    detail: Mapped[dict | None] = mapped_column(JSONB)
    resolution: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
    resolved_at: Mapped[datetime | None] = mapped_column()

    __table_args__ = (Index("ix_review_task_state", "state", "assignee"),)


class DocumentProcessingJob(Base):
    """资料处理的持久化任务与死信记录。每次重放创建新的 job_id。"""

    __tablename__ = "document_processing_job"

    job_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    owner: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_teams: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    upload_path: Mapped[str | None] = mapped_column(String(1024))
    revision_id: Mapped[str | None] = mapped_column(String(96))
    object_key: Mapped[str | None] = mapped_column(String(1024))
    object_version_id: Mapped[str | None] = mapped_column(String(255))
    upload_content_hash: Mapped[str | None] = mapped_column(String(64))
    ingestion_run_id: Mapped[str | None] = mapped_column(String(96))
    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column()
    security_id: Mapped[str | None] = mapped_column(String(64))
    thesis_id: Mapped[str | None] = mapped_column(String(64))
    view: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    result: Mapped[dict | None] = mapped_column(JSONB)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
    started_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        Index("ix_document_job_owner_status", "owner", "status", "created_at"),
        CheckConstraint("attempt_count >= 1", name="document_job_attempt_positive"),
    )


class IngestionReview(Base):
    """资料处理统一人工复核队列，不要求已经存在 thesis。"""

    __tablename__ = "ingestion_review"

    review_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    review_type: Mapped[str] = mapped_column(String(32), nullable=False)
    document_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    job_id: Mapped[str | None] = mapped_column(String(96))
    event_id: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    assignee: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    security_candidates: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at_column()
    resolved_at: Mapped[datetime | None] = mapped_column()

    __table_args__ = (Index("ix_ingestion_review_queue", "assignee", "status", "created_at"),)


class AdjudicationDecision(Base):
    """导师裁决结果；与程序化预标注分开存储，作为独立评测依据。"""

    __tablename__ = "adjudication_decision"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hypothesis: Mapped[str] = mapped_column(String(255), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by: Mapped[str] = mapped_column(String(64), nullable=False)
    decided_at: Mapped[datetime] = created_at_column()


class AuditLog(Base):
    """审计日志。记录查看、创建、编辑、确认、导出和模型调用（FR-A-003）。"""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    object_id: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSONB)
    model_version: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        Index("ix_audit_object", "object_type", "object_id"),
        Index("ix_audit_actor_time", "actor", "occurred_at"),
    )


class DataQualityResult(Base):
    """质量规则执行结果。阻断级失败不得进入正式信号和评测集。"""

    __tablename__ = "data_quality_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[str] = mapped_column(String(32), nullable=False)
    object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    object_id: Mapped[str | None] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    quarantined: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    checked_at: Mapped[datetime] = created_at_column()

    __table_args__ = (Index("ix_dq_rule_passed", "rule_id", "passed"),)
