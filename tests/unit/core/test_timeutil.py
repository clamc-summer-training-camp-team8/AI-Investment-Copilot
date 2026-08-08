"""时间语义约束。

数据分析说明书 T9：必须同时保存事实发生、公开披露、数据入库、AI 生成四类时间。
任何收益检验只能使用信号生成时已经公开可得的信息。
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.core.timeutil import (
    BUSINESS_TZ,
    NaiveDatetimeError,
    business_date,
    ensure_aware,
    from_naive_utc,
    is_leakage,
    next_observable_day,
)


def test_naive_datetime_必须显式声明时区() -> None:
    """拦截样例交付包里的时区混用：台账 xlsx 是 naive UTC，CSV/JSON 是业务时区。"""
    with pytest.raises(NaiveDatetimeError):
        ensure_aware(datetime(2026, 3, 31, 12, 0))


def test_显式声明时区后可入库() -> None:
    result = ensure_aware(datetime(2026, 3, 31, 12, 0), assume=BUSINESS_TZ)
    assert result.tzinfo is BUSINESS_TZ


def test_台账naive_utc转业务时区() -> None:
    """xlsx 与 CSV 存在 8 小时系统性偏差，转换后应落在同一日的 20 点。"""
    result = from_naive_utc(datetime(2026, 3, 31, 12, 0))
    assert result.hour == 20
    assert result.date() == business_date(result)


def test_跨时区取日历日不错位() -> None:
    """UTC 的 2026-03-31 23:00 在业务时区已是 4 月 1 日。直接取 .date() 会错一天。"""
    utc_late = datetime(2026, 3, 31, 23, 0, tzinfo=UTC)
    assert utc_late.date().day == 31
    assert business_date(utc_late).day == 1


def test_披露晚于生成即为泄露() -> None:
    """DQ-003 阻断级规则。"""
    disclosure = datetime(2026, 4, 2, 9, 0, tzinfo=BUSINESS_TZ)
    generated = datetime(2026, 4, 1, 9, 0, tzinfo=BUSINESS_TZ)
    assert is_leakage(disclosure, generated) is True


def test_披露等于生成不算泄露() -> None:
    """边界条件：DQ-003 的判定是 disclosure_time <= generated_at。"""
    moment = datetime(2026, 4, 1, 9, 0, tzinfo=BUSINESS_TZ)
    assert is_leakage(moment, moment) is False


def test_跨时区泄露判定按业务时区归一() -> None:
    """UTC 的 01:00 等于业务时区的 09:00，不应误判为泄露。"""
    disclosure = datetime(2026, 4, 1, 1, 0, tzinfo=UTC)
    generated = datetime(2026, 4, 1, 9, 0, tzinfo=BUSINESS_TZ)
    assert is_leakage(disclosure, generated) is False


def test_收益窗口起点为下一日() -> None:
    """MET-004 规定从首次可得时间的下一可交易时点开始。

    当前只处理日历日，交易日历需接入行情数据源后替换（GAP-003 未关闭）。
    """
    available = datetime(2026, 4, 1, 15, 30, tzinfo=BUSINESS_TZ)
    assert next_observable_day(available).isoformat() == "2026-04-02"


def test_其他时区输入归一后再取窗口起点() -> None:
    available = datetime(2026, 4, 1, 20, 0, tzinfo=ZoneInfo("America/New_York"))
    assert next_observable_day(available).isoformat() == "2026-04-03"
