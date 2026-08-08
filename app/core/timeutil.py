"""时间语义工具。

数据分析说明书 Table 10 要求同时保存四类时间：事实发生时间、公开披露时间、
数据入库时间、AI 信号生成时间。任何收益检验只能使用信号生成时已公开可得的信息。

字段字典 FLD-002/006/008 统一规定业务时区为 Asia/Shanghai。样例交付包中
台账 xlsx 与 CSV/JSON 存在 8 小时系统性偏差（xlsx 为 naive UTC），因此这里
禁止 naive datetime 直接入库，必须显式声明来源时区。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

BUSINESS_TZ = ZoneInfo("Asia/Shanghai")
BUSINESS_TZ_NAME = "Asia/Shanghai"


class NaiveDatetimeError(ValueError):
    """禁止 naive datetime 静默入库。"""


def now() -> datetime:
    """当前业务时区时间，带时区信息。"""
    return datetime.now(tz=BUSINESS_TZ)


def ensure_aware(value: datetime, *, assume: ZoneInfo | None = None) -> datetime:
    """确保 datetime 带时区。

    naive 输入必须显式给出 ``assume`` 时区，否则抛错。这条约束用于拦截样例包里
    的时区混用问题，避免 DQ-003（披露时间不得晚于信号生成时间）产生错误结论。
    """
    if value.tzinfo is not None:
        return value
    if assume is None:
        raise NaiveDatetimeError(f"naive datetime {value!r} 缺少时区；请显式指定来源时区后再入库")
    return value.replace(tzinfo=assume)


def to_business(value: datetime, *, assume: ZoneInfo | None = None) -> datetime:
    """归一到业务时区，便于跨来源比较。"""
    return ensure_aware(value, assume=assume).astimezone(BUSINESS_TZ)


def from_naive_utc(value: datetime) -> datetime:
    """把台账 xlsx 中的 naive UTC 时间转为业务时区。"""
    return value.replace(tzinfo=UTC).astimezone(BUSINESS_TZ)


def business_date(value: datetime, *, assume: ZoneInfo | None = None) -> date:
    """取业务时区下的日历日。跨时区直接取 .date() 会错位一天。"""
    return to_business(value, assume=assume).date()


def is_leakage(disclosure_time: datetime, generated_at: datetime) -> bool:
    """DQ-003：信号生成时间早于事件披露时间即为未来数据泄露。"""
    return to_business(disclosure_time) > to_business(generated_at)


def next_observable_day(available_at: datetime) -> date:
    """收益窗口起点：首次可得时间的下一个日历日。

    指标字典 MET-004 规定"从首次可得时间下一可交易时点开始"。这里只处理日历日，
    交易日历需接入行情数据源后替换（对应缺口 GAP-003，复权与可交易时点待业务确认）。
    """
    return business_date(available_at) + timedelta(days=1)
