from __future__ import annotations

from dataclasses import replace
from datetime import date

from fastapi.testclient import TestClient

from app.api.deps import get_uow
from app.api.main import create_app
from app.core.domain import (
    CoverageCompanyRecord,
    CoverageSectorRecord,
    SecurityRecord,
    ThesisRecord,
)
from app.core.enums import ThesisStatus
from tests.fakes import build_fake_uow


class MemoryCoverageRepo:
    available = True

    def __init__(self) -> None:
        self.sectors: dict[str, CoverageSectorRecord] = {}
        self.companies: dict[str, CoverageCompanyRecord] = {}

    def list_sectors(self):
        return [replace(item) for item in self.sectors.values()]

    def get_sector(self, sector_id: str):
        item = self.sectors.get(sector_id)
        return replace(item) if item else None

    def add_sector(self, record: CoverageSectorRecord) -> None:
        self.sectors[record.sector_id] = replace(record)

    def update_sector(self, record: CoverageSectorRecord) -> None:
        self.sectors[record.sector_id] = replace(record)

    def list_companies(self, sector_id: str | None = None):
        return [
            replace(item)
            for item in self.companies.values()
            if sector_id is None or item.sector_id == sector_id
        ]

    def get_company(self, coverage_company_id: str):
        item = self.companies.get(coverage_company_id)
        return replace(item) if item else None

    def find_company(self, *, sector_id: str, security_id: str):
        return next(
            (
                replace(item)
                for item in self.companies.values()
                if item.sector_id == sector_id and item.security_id == security_id
            ),
            None,
        )

    def add_company(self, record: CoverageCompanyRecord) -> None:
        self.companies[record.coverage_company_id] = replace(record)

    def update_company(self, record: CoverageCompanyRecord) -> None:
        self.companies[record.coverage_company_id] = replace(record)


def test_coverage_sector_search_rename_company_add_and_pause() -> None:
    application = create_app()
    uow = build_fake_uow()
    uow.coverage = MemoryCoverageRepo()
    uow.securities.add(
        SecurityRecord(
            security_id="600519", name="贵州茅台", ticker="600519.SH", industry="食品饮料-白酒"
        )
    )
    application.dependency_overrides[get_uow] = lambda: uow
    headers = {"X-User-Id": "analyst-mvp"}

    with TestClient(application) as client:
        created_sector = client.post(
            "/api/coverage/sectors", json={"name": "大消费"}, headers=headers
        )
        assert created_sector.status_code == 201
        sector_id = created_sector.json()["sector_id"]

        assert client.get("/api/coverage?query=半导体", headers=headers).json() == []
        assert client.get("/api/coverage?query=消费", headers=headers).json()[0]["name"] == "大消费"

        renamed = client.patch(
            f"/api/coverage/sectors/{sector_id}", json={"name": "消费"}, headers=headers
        )
        assert renamed.status_code == 200
        assert renamed.json()["name"] == "消费"

        created_company = client.post(
            f"/api/coverage/sectors/{sector_id}/companies",
            json={"security_id": "600519"},
            headers=headers,
        )
        assert created_company.status_code == 201
        company = created_company.json()
        assert company["market"] == "A股"
        assert company["status"] == "待建档"
        assert company["thesis_count"] == 0

        paused = client.patch(
            f"/api/coverage/companies/{company['coverage_company_id']}",
            json={"status": "暂停覆盖"},
            headers=headers,
        )
        assert paused.status_code == 200
        assert paused.json()["status"] == "暂停覆盖"

    application.dependency_overrides.clear()


def test_coverage_only_counts_real_thesis_in_maintenance() -> None:
    application = create_app()
    uow = build_fake_uow()
    uow.coverage = MemoryCoverageRepo()
    uow.securities.add(
        SecurityRecord(security_id="000538", name="云南白药", ticker="000538.SZ", industry="医药")
    )
    uow.thesis.add(
        ThesisRecord(
            thesis_id="THS-000538",
            security_id="000538",
            title="演示逻辑",
            direction="观察",
            core_view="仅用于演示",
            established_on=date(2026, 1, 1),
            owner="analyst-mvp",
            status=ThesisStatus.VALIDATING,
            is_illustrative=True,
        )
    )
    application.dependency_overrides[get_uow] = lambda: uow
    headers = {"X-User-Id": "analyst-mvp"}

    with TestClient(application) as client:
        company = client.get("/api/coverage", headers=headers).json()[0]["companies"][0]
        assert company["thesis_count"] == 0
        assert company["status"] == "待建档"
        assert company["thesis_id"] is None

        thesis = uow.thesis.get("THS-000538")
        assert thesis is not None
        thesis.is_illustrative = False
        thesis.status = ThesisStatus.DRAFT
        uow.thesis.update(thesis)

        company = client.get("/api/coverage", headers=headers).json()[0]["companies"][0]
        assert company["thesis_count"] == 0
        assert company["status"] == "待建档"

        thesis.status = ThesisStatus.VALIDATING
        uow.thesis.update(thesis)

        company = client.get("/api/coverage", headers=headers).json()[0]["companies"][0]
        assert company["thesis_count"] == 1
        assert company["status"] == "正常覆盖"
        assert company["thesis_id"] == "THS-000538"

    application.dependency_overrides.clear()


def test_coverage_counts_current_observation_snapshot_as_maintained_logic() -> None:
    application = create_app()
    uow = build_fake_uow()
    uow.coverage = MemoryCoverageRepo()
    uow.securities.add(
        SecurityRecord(security_id="000538", name="云南白药", ticker="000538.SZ", industry="医药")
    )
    uow.thesis.add(
        ThesisRecord(
            thesis_id="THS-000538-OBS",
            security_id="000538",
            title="云南白药季度观察",
            direction="观察",
            core_view="观察逻辑",
            established_on=date(2026, 1, 1),
            owner="analyst-mvp",
            status=ThesisStatus.VALIDATING,
            thesis_kind="observation",
            is_illustrative=False,
        )
    )
    application.dependency_overrides[get_uow] = lambda: uow

    with TestClient(application) as client:
        company = client.get("/api/coverage", headers={"X-User-Id": "analyst-mvp"}).json()[0]["companies"][0]
        assert company["thesis_count"] == 1
        assert company["status"] == "正常覆盖"
        assert company["thesis_id"] == "THS-000538-OBS"

    application.dependency_overrides.clear()
