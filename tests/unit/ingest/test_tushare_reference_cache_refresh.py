from datetime import UTC, datetime

import pytest

from app.ingest.market_sources import MarketSourceError
from scripts.refresh_tushare_reference_cache import _bind_source, endpoint_can_attempt


def test_trade_cal未到一小时时拒绝再次调用() -> None:
    now = datetime(2026, 8, 31, 2, 0, tzinfo=UTC)
    assert not endpoint_can_attempt(
        "2026-08-31T01:30:01+00:00",
        now=now,
        minimum_interval_seconds=3600,
    )
    assert endpoint_can_attempt(
        "2026-08-31T01:00:00+00:00",
        now=now,
        minimum_interval_seconds=3600,
    )


def test频控时间必须带时区() -> None:
    with pytest.raises(MarketSourceError, match="缺少时区"):
        endpoint_can_attempt(
            "2026-08-31T01:00:00",
            now=datetime(2026, 8, 31, 2, 0, tzinfo=UTC),
            minimum_interval_seconds=3600,
        )


def test_参考缓存禁止混用不同APIOrigin() -> None:
    state: dict[str, object] = {"files": {}, "endpoints": {}}
    _bind_source(state, api_origin="https://first.example")
    with pytest.raises(MarketSourceError, match="API Origin"):
        _bind_source(state, api_origin="https://second.example")


def test_既有无身份缓存必须迁移到新目录() -> None:
    state: dict[str, object] = {
        "files": {"trade_cal/legacy.json": {}},
        "endpoints": {},
    }
    with pytest.raises(MarketSourceError, match="新的缓存目录"):
        _bind_source(state, api_origin="https://example.test")
