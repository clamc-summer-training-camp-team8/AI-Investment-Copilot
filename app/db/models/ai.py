'''Agent Runtime、模型调用与恢复信息的持久化模型。'''

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, created_at_column, updated_at_column


class AiRun(Base):
    '''一次统一 Runtime 执行；候选结果仍须人工确认后进入正式业务表。'''

    __tablename__ = 'ai_run'

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column()
    model_version: Mapped[str | None] = mapped_column(String(255))
    prompt_version: Mapped[str | None] = mapped_column(String(255))
    retrieval_versions: Mapped[list | None] = mapped_column(JSONB)
    schema_name: Mapped[str | None] = mapped_column(String(64))
    degraded_reason: Mapped[str | None] = mapped_column(String(128))
    errors: Mapped[list | None] = mapped_column(JSONB)
    transitions: Mapped[list | None] = mapped_column(JSONB)
    result: Mapped[dict | None] = mapped_column(JSONB)
    verification: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    model_calls: Mapped[list[ModelCallLog]] = relationship(
        back_populates='run', cascade='all, delete-orphan'
    )

    __table_args__ = (
        Index('ix_ai_run_status_created', 'status', 'created_at'),
        Index('ix_ai_run_task_started', 'task', 'started_at'),
    )


class ModelCallLog(Base):
    '''单次 Provider 调用的用量、延迟和估算成本。'''

    __tablename__ = 'model_call_log'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey('ai_run.run_id', ondelete='CASCADE'), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(128))
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    cost_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 8), nullable=False, default=Decimal('0')
    )
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default='CNY')
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error_code: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict | None] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = created_at_column()

    run: Mapped[AiRun] = relationship(back_populates='model_calls')

    __table_args__ = (
        Index('ix_model_call_run', 'run_id'),
        Index('ix_model_call_model_time', 'model_version', 'occurred_at'),
    )
