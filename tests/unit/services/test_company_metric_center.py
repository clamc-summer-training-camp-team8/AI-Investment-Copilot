from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import httpx

import app.services.company_metric_center as metric_center
from app.core.domain import MetricDefinitionRecord, ObservationRecord, SecurityRecord
from app.services.company_metric_center import _fetch_financials_sina, _fetch_market
from tests.fakes import build_fake_uow


def test_fetch_market_skips_eastmoney_placeholders_without_failing() -> None:
    row = "2026-08-28,110.10,--,113.00,109.80,123456,987654321,2.9,--,2.10,--"
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"data": {"klines": [row]}},
    )
    client = SimpleNamespace(get=lambda *args, **kwargs: response)

    observations = _fetch_market(client, "002594", "002594.SZ")

    assert {item.metric_id for item in observations} == {
        "MKT-OPEN-D",
        "MKT-HIGH-D",
        "MKT-LOW-D",
        "MKT-CHANGE-D",
        "MKT-AMPLITUDE-D",
        "MKT-VOLUME-D",
        "MKT-AMOUNT-D",
    }


def test_fetch_market_falls_back_to_sina_daily_prices() -> None:
    sina_response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {
            "result": {
                "data": [
                    {
                        "day": "2026-08-28",
                        "open": "97",
                        "high": "99",
                        "low": "96",
                        "close": "98",
                        "volume": "10000",
                    },
                    {
                        "day": "2026-08-31",
                        "open": "97",
                        "high": "98",
                        "low": "89",
                        "close": "91",
                        "volume": "20000",
                    },
                ]
            }
        },
    )

    def get(url, **kwargs):
        if "eastmoney.com" in url:
            raise httpx.ConnectError("行情源不可用")
        return sina_response

    observations = _fetch_market(SimpleNamespace(get=get), "300274", "300274.SZ")

    assert {item.metric_id for item in observations} >= {
        "MKT-OPEN-D",
        "MKT-HIGH-D",
        "MKT-LOW-D",
        "MKT-CLOSE-D",
        "MKT-VOLUME-D",
        "MKT-CHANGE-D",
        "MKT-CHANGE-PCT-D",
        "MKT-AMPLITUDE-D",
    }


def test_refresh_security_metrics_stores_eastmoney_kline_rows(monkeypatch) -> None:
    row = "2026-08-28,110.10,112.20,113.00,109.80,123456,987654321,2.9,1.91,2.10,3.4"
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"data": {"klines": [row]}},
    )

    class FakeClient:
        def __enter__(self):
            return SimpleNamespace(get=lambda *args, **kwargs: response)

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(metric_center.httpx, "Client", lambda **kwargs: FakeClient())
    for name in ("_fetch_valuation", "_fetch_industry", "_fetch_financials", "_fetch_macro"):
        monkeypatch.setattr(metric_center, name, lambda *args: [])

    uow = build_fake_uow()
    uow.securities.add(SecurityRecord(security_id="002594", name="比亚迪", ticker="002594.SZ"))
    result = metric_center.refresh_security_metrics(uow, "002594")

    assert result["errors"] == []
    assert result["inserted"] == 10
    assert {item.metric_id for item in uow.observations.items} == {
        "MKT-OPEN-D",
        "MKT-HIGH-D",
        "MKT-LOW-D",
        "MKT-CLOSE-D",
        "MKT-CHANGE-D",
        "MKT-AMPLITUDE-D",
        "MKT-VOLUME-D",
        "MKT-AMOUNT-D",
        "MKT-TURNOVER-D",
        "MKT-CHANGE-PCT-D",
    }


def test_store_is_idempotent_for_duplicate_source_rows_and_repeated_refreshes() -> None:
    uow = build_fake_uow()
    row = metric_center.RawObservation(
        "VAL-PE-TTM-D", "2026-08-28", date(2026, 8, 28), Decimal("12.34"), "倍", "日值"
    )

    assert metric_center._store(uow, "002594", [row, row]) == 1
    assert metric_center._store(uow, "002594", [row]) == 0
    assert len(uow.observations.items) == 1


def test_metric_center_merges_database_catalog_with_observations() -> None:
    uow = build_fake_uow()
    uow.securities.add(SecurityRecord(security_id="002594", name="比亚迪", ticker="002594.SZ"))
    uow.metrics.items[("MET-001", "v1.0")] = MetricDefinitionRecord(
        metric_id="MET-001",
        version="v1.0",
        name="营业收入同比",
        unit="%",
        category="经营",
        definition="营业收入相对上年同期的变化率。",
        frequency="季度",
        period_type="单季度",
        source_id="financial-api",
        status="已确认",
    )
    uow.observations.add(
        ObservationRecord(
            security_id="002594",
            metric_id="MET-001",
            period="2026Q1",
            observation_date=date(2026, 4, 30),
            unit="%",
            actual_value=Decimal("12.34"),
        )
    )

    result = metric_center.metric_center(uow, "002594")

    item = next(metric for metric in result if metric["metric_id"] == "MET-001")
    assert item["name"] == "营业收入同比"
    assert item["category"] == "财务与运营"
    assert item["definition"] == "营业收入相对上年同期的变化率。"
    assert item["frequency"] == "季度"
    assert item["latest_value"] == "12.34"


def test_fetch_financials_sina_maps_reports_without_akshare() -> None:
    payload = {
        "result": {
            "data": {
                "report_date": [{"date_value": "2025-12-31"}],
                "report_list": {
                    "2025-12-31": {
                        "publish_date": "2026-04-30",
                        "rCurrency": "人民币",
                        "data": [
                            {"item_title": "营业总收入", "item_value": "1000000"},
                            {"item_title": "营业收入同比", "item_value": "8.8%"},
                            {"item_title": "研发费用", "item_value": "10000"},
                            {"item_title": "归属于母公司股东的净利润", "item_value": "120000"},
                            {"item_title": "资产负债率", "item_value": "35.5"},
                            {"item_title": "存货", "item_value": "80000"},
                        ],
                    }
                },
            }
        }
    }

    class FakeClient:
        def get(self, *args, **kwargs):
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)

    rows = _fetch_financials_sina(FakeClient(), "600519", "600519.SH")

    by_metric = {row.metric_id: row for row in rows}
    assert by_metric["FIN-REVENUE-CUM"].value == Decimal("1000000")
    assert by_metric["FIN-RD-RATIO"].value == Decimal("1")
    assert by_metric["FIN-REVENUE-YOY"].value == Decimal("8.8")
    assert by_metric["FIN-DEBT-RATIO"].unit == "%"
    assert by_metric["FIN-INVENTORY-END"].unit == "CNY"
