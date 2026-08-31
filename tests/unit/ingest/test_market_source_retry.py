from __future__ import annotations

import pytest

from app.ingest.market_source_retry import MarketRetryEvent, call_market_source
from app.ingest.market_sources import MarketSourceError


def test_瞬时错误按上限重试并记录脱敏事件() -> None:
    attempts = 0
    events: list[MarketRetryEvent] = []

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("timeout token=secret-token-value-123456")
        return "ok"

    result = call_market_source(
        "akshare.600276",
        operation,
        max_attempts=3,
        wait_seconds=0,
        secrets=("secret-token-value-123456",),
        events=events,
    )
    assert result == "ok"
    assert attempts == 3
    assert len(events) == 2
    assert all("secret-token" not in event.reason for event in events)


def test_最终失败转为稳定市场源错误且不泄露Token() -> None:
    with pytest.raises(MarketSourceError) as caught:
        call_market_source(
            "tushare.daily",
            lambda: (_ for _ in ()).throw(RuntimeError("Token: abcdefghijklmnopqrstuvwxyz")),
            max_attempts=2,
            wait_seconds=0,
        )
    assert "abcdefghijklmnopqrstuvwxyz" not in str(caught.value)
    assert "[REDACTED]" in str(caught.value)
