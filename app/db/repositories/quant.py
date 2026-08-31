"""量化不可变快照仓储。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.domain import (
    QuantBacktestRecord,
    QuantMarketDatasetRecord,
    QuantSignalSetRecord,
)
from app.db.models.quant import QuantBacktestRun, QuantMarketDataset, QuantSignalSet


def _dataset(row: QuantMarketDataset) -> QuantMarketDatasetRecord:
    return QuantMarketDatasetRecord(
        dataset_id=row.dataset_id,
        data_version=row.data_version,
        manifest_path=row.manifest_path,
        manifest_sha256=row.manifest_sha256,
        source_policy_id=row.source_policy_id,
        authorization_status=row.authorization_status,
        adjustment=row.adjustment,
        coverage_start=row.coverage_start,
        coverage_end=row.coverage_end,
        securities=list(row.securities),
        capabilities=dict(row.capabilities),
        limitations=list(row.limitations),
        status=row.status,
        frozen_by=row.frozen_by,
        frozen_at=row.frozen_at,
    )


def _signal_set(row: QuantSignalSet) -> QuantSignalSetRecord:
    return QuantSignalSetRecord(
        signal_set_id=row.signal_set_id,
        name=row.name,
        version=row.version,
        content_sha256=row.content_sha256,
        signals=list(row.signals),
        signal_count=row.signal_count,
        human_confirmed_only=row.human_confirmed_only,
        evaluation_track=row.evaluation_track,
        status=row.status,
        frozen_by=row.frozen_by,
        frozen_at=row.frozen_at,
    )


def _run(row: QuantBacktestRun) -> QuantBacktestRecord:
    return QuantBacktestRecord(
        run_id=row.run_id,
        name=row.name,
        market_dataset_id=row.market_dataset_id,
        signal_set_id=row.signal_set_id,
        methodology_version=row.methodology_version,
        parameters=dict(row.parameters),
        result=dict(row.result),
        evaluation_track=row.evaluation_track,
        requested_by=row.requested_by,
        generated_at=row.generated_at,
    )


class SqlQuantRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_market_dataset(self, record: QuantMarketDatasetRecord) -> None:
        self._session.add(QuantMarketDataset(**record.__dict__))
        self._session.flush()

    def get_market_dataset(self, dataset_id: str) -> QuantMarketDatasetRecord | None:
        row = self._session.get(QuantMarketDataset, dataset_id)
        return None if row is None else _dataset(row)

    def list_market_datasets(self) -> list[QuantMarketDatasetRecord]:
        rows = self._session.scalars(
            select(QuantMarketDataset).order_by(QuantMarketDataset.frozen_at.desc())
        )
        return [_dataset(row) for row in rows]

    def add_signal_set(self, record: QuantSignalSetRecord) -> None:
        self._session.add(QuantSignalSet(**record.__dict__))
        self._session.flush()

    def get_signal_set(self, signal_set_id: str) -> QuantSignalSetRecord | None:
        row = self._session.get(QuantSignalSet, signal_set_id)
        return None if row is None else _signal_set(row)

    def list_signal_sets(self) -> list[QuantSignalSetRecord]:
        rows = self._session.scalars(
            select(QuantSignalSet).order_by(QuantSignalSet.frozen_at.desc())
        )
        return [_signal_set(row) for row in rows]

    def add_backtest(self, record: QuantBacktestRecord) -> None:
        if self._session.get(QuantBacktestRun, record.run_id) is None:
            self._session.add(QuantBacktestRun(**record.__dict__))
            self._session.flush()

    def get_backtest(self, run_id: str) -> QuantBacktestRecord | None:
        row = self._session.get(QuantBacktestRun, run_id)
        return None if row is None else _run(row)

    def list_backtests(self, requested_by: str, *, limit: int = 50) -> list[QuantBacktestRecord]:
        rows = self._session.scalars(
            select(QuantBacktestRun)
            .where(QuantBacktestRun.requested_by == requested_by)
            .order_by(QuantBacktestRun.generated_at.desc())
            .limit(limit)
        )
        return [_run(row) for row in rows]
