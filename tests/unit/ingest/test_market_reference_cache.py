from __future__ import annotations

import json
from datetime import date
from hashlib import sha256
from pathlib import Path

import pytest

from app.ingest.market_reference_cache import (
    load_market_cap_cache,
    load_price_limit_cache,
    load_trading_calendar_cache,
)
from app.ingest.market_sources import MarketSourceError


def _write_cache(root: Path) -> Path:
    path = root / "daily_basic" / "2026-08-28.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "tushare-daily-basic-cache-v1",
                "status": "complete",
                "trading_date": "2026-08-28",
                "rows": [
                    {
                        "security_id": "688981",
                        "total_market_cap": "1000000",
                        "circulating_market_cap": "800000",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    state = {
        "schema_version": "tushare-reference-cache-state-v1",
        "files": {
            "daily_basic/2026-08-28.json": {
                "endpoint": "daily_basic",
                "sha256": sha256(path.read_bytes()).hexdigest(),
            }
        },
        "endpoints": {},
    }
    (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return path


def test_缓存按哈希读取点时市值(tmp_path: Path) -> None:
    _write_cache(tmp_path)
    loaded = load_market_cap_cache(tmp_path, start=date(2026, 8, 1), end=date(2026, 8, 31))
    assert loaded.row_count == 1
    assert loaded.by_security["688981"][date(2026, 8, 28)] == 1000000


def test_缓存哈希漂移时阻断候选构建(tmp_path: Path) -> None:
    path = _write_cache(tmp_path)
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(MarketSourceError, match="哈希漂移"):
        load_market_cap_cache(tmp_path, start=date(2026, 8, 1), end=date(2026, 8, 31))


def test_交易日历只消费同年最新快照(tmp_path: Path) -> None:
    old_path = tmp_path / "trade_cal" / "SSE-2026-old.json"
    new_path = tmp_path / "trade_cal" / "SSE-2026-new.json"
    old_payload = {
        "schema_version": "tushare-trade-calendar-cache-v1",
        "sessions": [{"calendar_date": "2026-08-28", "is_open": False}],
    }
    new_payload = {
        "schema_version": "tushare-trade-calendar-cache-v1",
        "sessions": [
            {"calendar_date": "2026-08-28", "is_open": True},
            {"calendar_date": "2026-08-29", "is_open": False},
        ],
    }
    old_path.parent.mkdir(parents=True)
    old_path.write_text(json.dumps(old_payload), encoding="utf-8")
    new_path.write_text(json.dumps(new_payload), encoding="utf-8")
    state = {
        "schema_version": "tushare-reference-cache-state-v1",
        "endpoints": {},
        "files": {
            "trade_cal/SSE-2026-old.json": {
                "endpoint": "trade_cal",
                "observed_date": "2026-12-31",
                "fetched_at": "2026-08-20T12:00:00+08:00",
                "sha256": sha256(old_path.read_bytes()).hexdigest(),
            },
            "trade_cal/SSE-2026-new.json": {
                "endpoint": "trade_cal",
                "observed_date": "2026-12-31",
                "fetched_at": "2026-08-30T12:00:00+08:00",
                "sha256": sha256(new_path.read_bytes()).hexdigest(),
            },
        },
    }
    (tmp_path / "state.json").write_text(json.dumps(state), encoding="utf-8")

    loaded = load_trading_calendar_cache(tmp_path, start=date(2026, 8, 28), end=date(2026, 8, 29))

    assert loaded.open_days == frozenset({date(2026, 8, 28)})
    assert loaded.session_days == frozenset({date(2026, 8, 28), date(2026, 8, 29)})
    assert loaded.files == ("trade_cal/SSE-2026-new.json",)


def test_历史参考缓存同时提供市值和涨跌停状态(tmp_path: Path) -> None:
    path = tmp_path / "reference_history" / "688981.json"
    payload = {
        "schema_version": "tushare-reference-history-cache-v1",
        "rows": [
            {
                "security_id": "688981",
                "trading_date": "2026-08-28",
                "total_market_cap": "1000000",
                "price_limit_observed": True,
                "limit_up": False,
                "limit_down": True,
            }
        ],
    }
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    state = {
        "schema_version": "tushare-reference-cache-state-v1",
        "endpoints": {},
        "files": {
            "reference_history/688981.json": {
                "endpoint": "reference_history",
                "sha256": sha256(path.read_bytes()).hexdigest(),
            }
        },
    }
    (tmp_path / "state.json").write_text(json.dumps(state), encoding="utf-8")

    market_caps = load_market_cap_cache(tmp_path, start=date(2026, 8, 28), end=date(2026, 8, 28))
    price_limits = load_price_limit_cache(tmp_path, start=date(2026, 8, 28), end=date(2026, 8, 28))

    assert market_caps.by_security["688981"][date(2026, 8, 28)] == 1000000
    assert price_limits.by_security["688981"][date(2026, 8, 28)].limit_down is True
