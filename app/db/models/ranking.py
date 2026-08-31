from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column


class LogicTopic(Base):
    """归一化投资逻辑主题；原 Thesis 保持为研究员正式业务对象。"""

    __tablename__ = "logic_topic"

    topic_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    security_id: Mapped[str] = mapped_column(
        ForeignKey("security.security_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_statement: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    horizon: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    topic_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    source_thesis_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        UniqueConstraint(
            "security_id", "normalized_statement", "direction", "horizon", "topic_version"
        ),
        Index("ix_logic_topic_scope", "security_id", "direction", "horizon", "status"),
    )


class LogicTopicRelation(Base):
    """主题到 Thesis、Hypothesis、Metric、Evidence 和切片的可追溯关系。"""

    __tablename__ = "logic_topic_relation"

    relation_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    topic_id: Mapped[str] = mapped_column(
        ForeignKey("logic_topic.topic_id", ondelete="CASCADE"), nullable=False
    )
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    object_id: Mapped[str] = mapped_column(String(255), nullable=False)
    relation: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    citation_locators: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    model_version: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        UniqueConstraint("topic_id", "object_type", "object_id", "relation"),
        Index("ix_logic_topic_relation_topic", "topic_id", "object_type", "status"),
    )


class RankingPriorSnapshot(Base):
    __tablename__ = "ranking_prior_snapshot"

    snapshot_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    security_id: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    horizon: Mapped[str] = mapped_column(String(16), nullable=False)
    as_of: Mapped[datetime] = mapped_column(nullable=False)
    ranker_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    generator_model_version: Mapped[str | None] = mapped_column(String(128))
    judge_model_version: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="generated")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        UniqueConstraint("security_id", "direction", "horizon", "as_of", "ranker_version"),
        Index(
            "ix_ranking_prior_snapshot_scope",
            "security_id",
            "direction",
            "horizon",
            "status",
            "as_of",
        ),
    )


class RankingPriorItem(Base):
    __tablename__ = "ranking_prior_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("ranking_prior_snapshot.snapshot_id", ondelete="CASCADE"), nullable=False
    )
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    object_id: Mapped[str] = mapped_column(String(192), nullable=False)
    base_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    base_score: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    judge_rank: Mapped[int | None] = mapped_column(Integer)
    judge_score: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    judge_confidence: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    final_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    final_score: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    feature_scores: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    reason_codes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    citation_locators: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")

    __table_args__ = (
        UniqueConstraint("snapshot_id", "object_type", "object_id"),
        Index("ix_ranking_prior_item_lookup", "snapshot_id", "object_type", "object_id"),
        Index("ix_ranking_prior_item_rank", "snapshot_id", "object_type", "final_rank"),
    )
