"""本地板块与公司覆盖目录仓储。"""

from __future__ import annotations

from sqlalchemy import inspect, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.domain import CoverageCompanyRecord, CoverageSectorRecord
from app.db.models.coverage import CoverageCompany, CoverageSector

_availability_cache: dict[int, bool] = {}


def _sector(row: CoverageSector) -> CoverageSectorRecord:
    return CoverageSectorRecord(
        sector_id=row.sector_id,
        name=row.name,
        code=row.code,
        description=row.description,
        status=row.status,
        sort_order=row.sort_order,
        updated_at=row.updated_at,
    )


def _company(row: CoverageCompany) -> CoverageCompanyRecord:
    return CoverageCompanyRecord(
        coverage_company_id=row.coverage_company_id,
        sector_id=row.sector_id,
        security_id=row.security_id,
        name=row.name,
        ticker=row.ticker,
        industry=row.industry,
        market=row.market,
        owner=row.owner,
        status=row.status,
        updated_at=row.updated_at,
    )


class SqlCoverageRepo:
    def __init__(self, session: Session) -> None:
        self._session = session
        bind = session.get_bind()
        # 覆盖目录表在旧库中可能尚未迁移。这里的探测不能阻断其它接口
        # （例如公司逻辑保存）；远程库短暂断开时退回只读视图即可。
        self.available = False
        if bind and id(bind) in _availability_cache:
            self.available = _availability_cache[id(bind)]
        elif bind:
            try:
                inspector = inspect(bind)
                self.available = inspector.has_table("coverage_sector") and inspector.has_table("coverage_company")
                _availability_cache[id(bind)] = self.available
            except SQLAlchemyError:
                self.available = False

    def list_sectors(self) -> list[CoverageSectorRecord]:
        rows = self._session.scalars(
            select(CoverageSector).order_by(CoverageSector.sort_order, CoverageSector.name)
        ).all()
        return [_sector(row) for row in rows]

    def get_sector(self, sector_id: str) -> CoverageSectorRecord | None:
        row = self._session.get(CoverageSector, sector_id)
        return None if row is None else _sector(row)

    def add_sector(self, record: CoverageSectorRecord) -> None:
        self._session.add(
            CoverageSector(
                sector_id=record.sector_id,
                name=record.name,
                code=record.code,
                description=record.description,
                status=record.status,
                sort_order=record.sort_order,
            )
        )
        self._session.flush()

    def update_sector(self, record: CoverageSectorRecord) -> None:
        row = self._session.get(CoverageSector, record.sector_id)
        if row is None:
            raise LookupError(f"coverage sector {record.sector_id} 不存在")
        row.name = record.name
        row.code = record.code
        row.description = record.description
        row.status = record.status
        row.sort_order = record.sort_order
        self._session.flush()

    def list_companies(self, sector_id: str | None = None) -> list[CoverageCompanyRecord]:
        statement = select(CoverageCompany).order_by(CoverageCompany.name, CoverageCompany.security_id)
        if sector_id:
            statement = statement.where(CoverageCompany.sector_id == sector_id)
        return [_company(row) for row in self._session.scalars(statement).all()]

    def get_company(self, coverage_company_id: str) -> CoverageCompanyRecord | None:
        row = self._session.get(CoverageCompany, coverage_company_id)
        return None if row is None else _company(row)

    def find_company(self, *, sector_id: str, security_id: str) -> CoverageCompanyRecord | None:
        row = self._session.scalar(
            select(CoverageCompany).where(
                CoverageCompany.sector_id == sector_id,
                CoverageCompany.security_id == security_id,
            )
        )
        return None if row is None else _company(row)

    def add_company(self, record: CoverageCompanyRecord) -> None:
        self._session.add(
            CoverageCompany(
                coverage_company_id=record.coverage_company_id,
                sector_id=record.sector_id,
                security_id=record.security_id,
                name=record.name,
                ticker=record.ticker,
                industry=record.industry,
                market=record.market,
                owner=record.owner,
                status=record.status,
            )
        )
        self._session.flush()

    def update_company(self, record: CoverageCompanyRecord) -> None:
        row = self._session.get(CoverageCompany, record.coverage_company_id)
        if row is None:
            raise LookupError(f"coverage company {record.coverage_company_id} 不存在")
        row.sector_id = record.sector_id
        row.name = record.name
        row.ticker = record.ticker
        row.industry = record.industry
        row.market = record.market
        row.owner = record.owner
        row.status = record.status
        self._session.flush()
