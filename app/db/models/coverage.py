"""本地研究覆盖目录与市场板块目录。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, updated_at_column


class MarketSector(Base):
    """市场侧板块字典，由市场数据同步任务维护。"""

    __tablename__ = "market_sector"

    market_sector_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="market")
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        UniqueConstraint("name", name="uq_market_sector_name"),
        Index("ix_market_sector_code", "code"),
    )


class CoverageSector(Base):
    """研究员本地维护的板块。"""

    __tablename__ = "coverage_sector"

    sector_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (UniqueConstraint("name", name="uq_coverage_sector_name"),)


class CoverageCompany(Base):
    """研究员本地维护的公司档案，与证券主数据保持关联。"""

    __tablename__ = "coverage_company"

    coverage_company_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sector_id: Mapped[str] = mapped_column(
        ForeignKey("coverage_sector.sector_id", ondelete="CASCADE"), nullable=False
    )
    security_id: Mapped[str] = mapped_column(
        ForeignKey("security.security_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    ticker: Mapped[str | None] = mapped_column(String(32))
    industry: Mapped[str | None] = mapped_column(String(128))
    market: Mapped[str | None] = mapped_column(String(32))
    owner: Mapped[str] = mapped_column(String(64), nullable=False, default="待分配")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="待建档")
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        UniqueConstraint("sector_id", "security_id", name="uq_coverage_company_sector_security"),
        Index("ix_coverage_company_sector", "sector_id"),
        Index("ix_coverage_company_security", "security_id"),
    )
