from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.api.deps import get_uow
from app.api.main import create_app
from app.core.domain import ObservationRecord, SecurityRecord
from tests.fakes import build_fake_uow


def test_security_resolve_uses_market_when_database_has_no_match(monkeypatch) -> None:
    from app.services.market_security import MarketSecurity

    monkeypatch.setattr(
        "app.api.routers.securities.lookup_market_security",
        lambda query: [MarketSecurity("000567", "海德股份", "000567.SZ", "多元金融")],
    )
    application = create_app()
    application.dependency_overrides[get_uow] = lambda: build_fake_uow()
    with TestClient(application) as client:
        response = client.get(
            "/api/securities/resolve?query=海德股份",
            headers={"X-User-Id": "analyst-mvp"},
        )
    assert response.status_code == 200
    assert response.json() == [
        {
            "security_id": "000567",
            "name": "海德股份",
            "ticker": "000567.SZ",
            "industry": "多元金融",
            "aliases": [],
            "source": "market",
        }
    ]
    application.dependency_overrides.clear()


def test_security_resolve_writes_market_master_and_reuses_it(monkeypatch) -> None:
    from app.services.market_security import MarketSecurity

    calls = 0

    def external_lookup(query: str) -> list[MarketSecurity]:
        nonlocal calls
        calls += 1
        return [MarketSecurity("601799", "星宇股份", "601799.SH", "汽车零部件")]

    monkeypatch.setattr("app.api.routers.securities.lookup_market_security", external_lookup)
    application = create_app()
    uow = build_fake_uow()
    application.dependency_overrides[get_uow] = lambda: uow
    with TestClient(application) as client:
        first = client.get(
            "/api/securities/resolve?query=601799", headers={"X-User-Id": "analyst-mvp"}
        )
        second = client.get(
            "/api/securities/resolve?query=星宇", headers={"X-User-Id": "analyst-mvp"}
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == 1
    assert second.json()[0]["source"] == "market_database"
    assert uow.securities.get("601799") is None
    assert uow.securities.search_market("601799")[0].name == "星宇股份"
    application.dependency_overrides.clear()


def test_security_creation_requires_master_data_role() -> None:
    application = create_app()
    application.dependency_overrides[get_uow] = lambda: build_fake_uow()
    with TestClient(application) as client:
        denied = client.post(
            "/api/securities",
            headers={"X-User-Id": "ordinary-researcher"},
            json={"security_id": "NEW001", "name": "新公司"},
        )
        allowed = client.post(
            "/api/securities",
            headers={"X-User-Id": "ordinary-researcher", "X-User-Teams": "security-admin"},
            json={"security_id": "NEW001", "name": "新公司"},
        )

    assert denied.status_code == 403
    assert allowed.status_code == 201
    application.dependency_overrides.clear()


def test_security_detail_returns_master_data() -> None:
    application = create_app()
    uow = build_fake_uow()
    uow.securities.add(
        SecurityRecord(
            security_id="002594",
            name="比亚迪",
            ticker="002594.SZ",
            industry="新能源汽车",
        )
    )
    application.dependency_overrides[get_uow] = lambda: uow
    with TestClient(application) as client:
        response = client.get("/api/securities/002594", headers={"X-User-Id": "analyst-mvp"})

    assert response.status_code == 200
    assert response.json() == {
        "security_id": "002594",
        "name": "比亚迪",
        "ticker": "002594.SZ",
        "industry": "新能源汽车",
        "aliases": [],
    }
    application.dependency_overrides.clear()


def test_coverage_overview_falls_back_to_securities_when_directory_is_unavailable() -> None:
    application = create_app()
    uow = build_fake_uow()
    uow.coverage = type("UnavailableCoverage", (), {"available": False})()
    uow.securities.add(
        SecurityRecord(
            security_id="600519",
            name="贵州茅台",
            ticker="600519.SH",
            industry="食品饮料-白酒",
        )
    )
    application.dependency_overrides[get_uow] = lambda: uow

    with TestClient(application) as client:
        response = client.get("/api/coverage", headers={"X-User-Id": "analyst-mvp"})

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["name"] == "大消费"
    assert payload[0]["companies"][0]["security_id"] == "600519"
    assert payload[0]["companies"][0]["status"] == "待建档"
    application.dependency_overrides.clear()


def test_company_metric_center_returns_latest_change_and_history() -> None:
    application = create_app()
    uow = build_fake_uow()
    uow.securities.add(SecurityRecord(security_id="002594", name="比亚迪", ticker="002594.SZ"))
    for period, observed_on, value in (
        ("2026-08-27", date(2026, 8, 27), Decimal("108.50")),
        ("2026-08-28", date(2026, 8, 28), Decimal("110.67")),
    ):
        uow.observations.add(
            ObservationRecord(
                security_id="002594",
                metric_id="MKT-CLOSE-D",
                period=period,
                observation_date=observed_on,
                unit="元",
                actual_value=value,
                period_type="日值",
            )
        )
    application.dependency_overrides[get_uow] = lambda: uow

    with TestClient(application) as client:
        response = client.get(
            "/api/securities/002594/metric-center", headers={"X-User-Id": "analyst-mvp"}
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["updated_at"] == "2026-08-28"
    assert payload["metrics"][0]["name"] == "前复权收盘价"
    assert payload["metrics"][0]["latest_value"] == "110.67"
    assert payload["metrics"][0]["previous_value"] == "108.50"
    assert len(payload["metrics"][0]["observations"]) == 2
    application.dependency_overrides.clear()


def test_company_metric_refresh_uses_real_refresh_service(monkeypatch) -> None:
    application = create_app()
    uow = build_fake_uow()
    uow.securities.add(SecurityRecord(security_id="002594", name="比亚迪", ticker="002594.SZ"))
    monkeypatch.setattr(
        "app.api.routers.securities.refresh_security_metrics",
        lambda active_uow, security_id: {
            "security_id": security_id,
            "fetched": 12,
            "inserted": 10,
            "errors": ["宏观统计: ConnectTimeout"],
        },
    )
    application.dependency_overrides[get_uow] = lambda: uow

    with TestClient(application) as client:
        response = client.post(
            "/api/securities/002594/metric-center/refresh",
            headers={"X-User-Id": "analyst-mvp"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "security_id": "002594",
        "fetched": 12,
        "inserted": 10,
        "errors": ["宏观统计: ConnectTimeout"],
    }
    application.dependency_overrides.clear()
