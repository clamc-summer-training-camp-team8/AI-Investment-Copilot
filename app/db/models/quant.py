"""P2 量化产品化的不可变数据集、信号集与运行快照。"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column


class QuantMarketDataset(Base):
    __tablename__ = "quant_market_dataset"

    dataset_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    data_version: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    manifest_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    source_policy_id: Mapped[str] = mapped_column(String(96), nullable=False)
    authorization_status: Mapped[str] = mapped_column(String(32), nullable=False)
    adjustment: Mapped[str] = mapped_column(String(16), nullable=False)
    coverage_start: Mapped[date] = mapped_column(Date, nullable=False)
    coverage_end: Mapped[date] = mapped_column(Date, nullable=False)
    securities: Mapped[list] = mapped_column(JSONB, nullable=False)
    capabilities: Mapped[dict] = mapped_column(JSONB, nullable=False)
    limitations: Mapped[list] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    frozen_by: Mapped[str] = mapped_column(String(64), nullable=False)
    frozen_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        CheckConstraint("status = 'frozen'", name="quant_market_dataset_frozen"),
        CheckConstraint("coverage_end >= coverage_start", name="quant_market_dataset_coverage"),
    )


class QuantSignalSet(Base):
    __tablename__ = "quant_signal_set"

    signal_set_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    signals: Mapped[list] = mapped_column(JSONB, nullable=False)
    signal_count: Mapped[int] = mapped_column(Integer, nullable=False)
    human_confirmed_only: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evaluation_track: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    frozen_by: Mapped[str] = mapped_column(String(64), nullable=False)
    frozen_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        CheckConstraint("status = 'frozen'", name="quant_signal_set_frozen"),
        CheckConstraint("human_confirmed_only", name="quant_signal_set_human_confirmed"),
        CheckConstraint(
            "evaluation_track = 'alpha_validation'", name="quant_signal_set_alpha_track"
        ),
        CheckConstraint("signal_count > 0", name="quant_signal_set_nonempty"),
    )


class QuantBacktestRun(Base):
    __tablename__ = "quant_backtest_run"

    run_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    market_dataset_id: Mapped[str] = mapped_column(
        ForeignKey("quant_market_dataset.dataset_id", ondelete="RESTRICT"), nullable=False
    )
    signal_set_id: Mapped[str] = mapped_column(
        ForeignKey("quant_signal_set.signal_set_id", ondelete="RESTRICT"), nullable=False
    )
    methodology_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    evaluation_track: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("evaluation_track = 'alpha_validation'", name="quant_backtest_alpha_track"),
        Index("ix_quant_backtest_owner_time", "requested_by", "generated_at"),
    )
