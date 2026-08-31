from __future__ import annotations

from datetime import date
from decimal import Decimal

from analytics.pipelines.universe import COMPANY_BY_ID
from app.ingest.market_sources import AksharePrimarySource, TushareSupplementSource


class FakeFrame:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        assert orient == "records"
        return self._rows


class FakeAkshare:
    __version__ = "test-akshare"

    def stock_zh_a_hist_tx(self, **kwargs: object) -> FakeFrame:
        assert kwargs["adjust"] in {"qfq", ""}
        return FakeFrame(
            [
                {
                    "date": date(2026, 8, 10),
                    "open": 10,
                    "close": 11,
                    "high": 12,
                    "low": 9,
                    "volume": 1000,
                    "amount": 10500,
                }
            ]
        )

    def stock_hk_daily(self, **kwargs: object) -> FakeFrame:
        assert kwargs == {"symbol": "00175", "adjust": "qfq"}
        return FakeFrame(
            [
                {
                    "date": "2026-08-11",
                    "open": 18,
                    "close": 19,
                    "high": 20,
                    "low": 17,
                    "volume": 2000,
                    "amount": 38000,
                }
            ]
        )

    def stock_zh_index_daily_tx(self, **kwargs: object) -> FakeFrame:
        return self.stock_zh_a_hist_tx(**kwargs)


class FakeAkshareHands(FakeAkshare):
    def stock_zh_a_hist_tx(self, **kwargs: object) -> FakeFrame:
        return FakeFrame(
            [
                {
                    "date": date(2026, 8, 10),
                    "open": 10,
                    "close": 10,
                    "high": 11,
                    "low": 9,
                    "volume": 100,
                    "amount": 100000,
                }
            ]
        )


def test_akshare主源规范化A股和港股并保留真实上游() -> None:
    source = AksharePrimarySource(FakeAkshare())
    a_rows = source.equity_quotes(
        COMPANY_BY_ID["688981"], start=date(2026, 8, 1), end=date(2026, 8, 31)
    )
    hk_rows = source.equity_quotes(
        COMPANY_BY_ID["00175"], start=date(2026, 8, 1), end=date(2026, 8, 31)
    )
    assert source.library_version == "test-akshare"
    assert a_rows[0].adjusted_close == Decimal(11)
    assert a_rows[0].traded_notional == Decimal(10500)
    assert a_rows[0].upstream_provider == "Tencent Finance"
    assert hk_rows[0].adjusted_close == Decimal(19)
    assert hk_rows[0].upstream_provider == "Sina Finance"
    raw_rows = source.a_share_raw_quotes(
        COMPANY_BY_ID["688981"], start=date(2026, 8, 1), end=date(2026, 8, 31)
    )
    assert raw_rows[0].source_interface == "akshare.stock_zh_a_hist_tx.raw"


def test_akshare按成交额量纲识别腾讯手数并转换成股() -> None:
    source = AksharePrimarySource(FakeAkshareHands())
    rows = source.equity_quotes(
        COMPANY_BY_ID["000538"], start=date(2026, 8, 1), end=date(2026, 8, 31)
    )
    assert rows[0].volume_shares == Decimal(10000)
    assert rows[0].source_interface.endswith(".volume_x100")


class FakePro:
    def daily_basic(self, **kwargs: object) -> FakeFrame:
        return FakeFrame(
            [
                {
                    "ts_code": "688981.SH",
                    "trade_date": "20260812",
                    "total_mv": "123.4",
                    "circ_mv": "100.1",
                }
            ]
        )

    def daily(self, **kwargs: object) -> FakeFrame:
        return FakeFrame(
            [
                {
                    "trade_date": "20260812",
                    "open": "9.00",
                    "high": "10.00",
                    "low": "9.00",
                    "close": "10.00",
                    "vol": "12",
                    "amount": "34",
                }
            ]
        )

    def stk_limit(self, **kwargs: object) -> FakeFrame:
        return FakeFrame([{"trade_date": "20260812", "up_limit": "10.00", "down_limit": "8.00"}])

    def trade_cal(self, **kwargs: object) -> FakeFrame:
        raise RuntimeError("抱歉，您没有接口访问权限，权限 Token: secret-token")


class FakeTushare:
    __version__ = "test-tushare"

    def __init__(self) -> None:
        self.token = ""
        self.pro = FakePro()
        self.last_pro_bar_api: object | None = None

    def set_token(self, token: str) -> None:
        self.token = token

    def pro_api(self, token: str) -> FakePro:
        assert token == self.token
        return self.pro

    def pro_bar(self, **kwargs: object) -> FakeFrame:
        self.last_pro_bar_api = kwargs.get("api")
        return FakeFrame(
            [
                {
                    "trade_date": "20260812",
                    "open": 9,
                    "close": 10,
                    "high": 10,
                    "low": 9,
                    "vol": 12,
                    "amount": 34,
                }
            ]
        )


def test_tushare只在显式Token下补充点时市值和涨跌停() -> None:
    module = FakeTushare()
    source = TushareSupplementSource("secret-token", module)
    batch = source.a_share_supplements(
        COMPANY_BY_ID["688981"], start=date(2026, 8, 1), end=date(2026, 8, 31)
    )
    assert batch.errors == ()
    assert batch.capabilities == {
        "point_in_time_market_cap": True,
        "price_limit_status": True,
    }
    assert batch.by_date[date(2026, 8, 12)].market_cap == Decimal("1234000.0")
    assert batch.by_date[date(2026, 8, 12)].limit_up is True
    fallback = source.fallback_a_share_quotes(
        COMPANY_BY_ID["688981"], start=date(2026, 8, 1), end=date(2026, 8, 31)
    )
    assert fallback[0].volume_shares == Decimal(1200)
    assert fallback[0].traded_notional == Decimal(34000)
    raw = source.daily_a_share_quotes(
        COMPANY_BY_ID["688981"], start=date(2026, 8, 1), end=date(2026, 8, 31)
    )
    assert raw[0].source_interface == "tushare.daily"
    snapshot = source.daily_basic_snapshot(
        (COMPANY_BY_ID["688981"], COMPANY_BY_ID["600276"]),
        trading_date=date(2026, 8, 12),
    )
    assert snapshot.upstream_row_count == 1
    assert snapshot.by_security["688981"].total_market_cap == Decimal("1234000.0")
    assert snapshot.missing_security_ids == ("600276",)
    market_cap_history = source.daily_basic_history(
        COMPANY_BY_ID["688981"], start=date(2026, 8, 1), end=date(2026, 8, 31)
    )
    assert market_cap_history[0].total_market_cap == Decimal("1234000.0")
    price_limit_history = source.price_limit_history(
        COMPANY_BY_ID["688981"], start=date(2026, 8, 1), end=date(2026, 8, 31)
    )
    assert price_limit_history[0].limit_up is True


def test_tushare自定义API地址同时用于pro接口和pro_bar() -> None:
    module = FakeTushare()
    source = TushareSupplementSource("secret-token", module, api_url="https://example.test")
    assert source.api_origin == "https://example.test"
    assert source.source_id == "tushare-compatible-supplement-v1"
    assert source.upstream_provider == "Tushare-compatible configured API"
    assert module.pro._DataApi__http_url == "https://example.test"
    source.fallback_a_share_quotes(
        COMPANY_BY_ID["688981"], start=date(2026, 8, 12), end=date(2026, 8, 12)
    )
    assert module.last_pro_bar_api is module.pro


def test_tushare权限探测只输出脱敏状态() -> None:
    source = TushareSupplementSource("secret-token", FakeTushare())
    probes = source.probe_permissions(COMPANY_BY_ID["600276"], trading_date=date(2026, 8, 12))
    assert {item.endpoint for item in probes} == {
        "daily",
        "pro_bar",
        "daily_basic",
        "stk_limit",
        "trade_cal",
    }
    calendar = next(item for item in probes if item.endpoint == "trade_cal")
    assert calendar.status == "permission_denied"
    assert calendar.reason is not None
    assert "secret-token" not in calendar.reason
    assert "[REDACTED]" in calendar.reason
