"""C 类管道：20 日行业中性超额收益标签（指标字典 MET-004）。

四条时间纪律，任何一条破了标签就不可用：

1. **T+1 起算。** 窗口从首次可得时间的**下一个可交易时点**开始。当天披露当天买入
   是拿不到的信息。
2. **窗口结束后才生成标签。** DQ-006 强制 `label_generated_at >= window_end`，
   窗口未结束一律标「待观察」，不用部分窗口的收益凑数。
3. **披露时间无具体时刻的按盘后处理。** 巨潮有 66% 的公告时间是 00:00，无法区分
   盘前盘后。假设盘前（当日可交易）会高估可得性，因此一律当盘后 → 次日起算。
   这个选择使标签更保守，不会因为时点假设制造虚假超额。
4. **基准事前确定。** 创业板指，选定后不换。

超额收益的算法委托给 `app.calc.deterministic.excess_return`，不在这里重写。离线与
线上算出不同数字是最伤信任的问题（analytics/README.md）。
"""

from __future__ import annotations

import json
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import cast

from analytics.pipelines.universe import BENCHMARK
from app.calc.deterministic import excess_return
from app.core.config import PROJECT_ROOT

RAW_DIR = PROJECT_ROOT / "real_data" / "raw"
WINDOW_DAYS = 20
QUANT = Decimal("0.0001")


@dataclass(frozen=True)
class ReturnLabel:
    """一条收益标签。

    `status` 只有两种取值：`已生成` 与 `待观察`。窗口没走完就是待观察，不给数字。
    """

    security_id: str
    disclosure_time: str
    window_start: str
    window_end: str
    security_return: Decimal | None
    benchmark_return: Decimal | None
    excess_return: Decimal | None
    status: str
    reason: str = ""


class QuoteBook:
    """行情查询。按交易日索引，只做定位与取值，不做插值。"""

    def __init__(self, path: Path | None = None) -> None:
        payload = json.loads((path or RAW_DIR / "quotes.json").read_text(encoding="utf-8"))
        self.data_version = str(payload.get("data_version", ""))
        raw_series = cast(dict[str, dict[str, str]], payload["series"])
        self._series: dict[str, dict[str, Decimal]] = {
            security: {day: Decimal(price) for day, price in series.items()}
            for security, series in raw_series.items()
        }
        self._days: dict[str, list[str]] = {
            security: sorted(series) for security, series in self._series.items()
        }

    @property
    def last_trading_day(self) -> str:
        return max(days[-1] for days in self._days.values() if days)

    def next_trading_day(self, security_id: str, after: str) -> str | None:
        """严格晚于 `after` 的第一个交易日。T+1 起算依赖它。"""
        days = self._days.get(security_id) or []
        index = bisect_right(days, after)
        return days[index] if index < len(days) else None

    def forward_day(self, security_id: str, start: str, offset: int) -> str | None:
        """`start` 之后第 `offset` 个交易日。"""
        days = self._days.get(security_id) or []
        index = bisect_left(days, start)
        if index >= len(days):
            return None
        target = index + offset
        return days[target] if target < len(days) else None

    def close(self, security_id: str, day: str) -> Decimal | None:
        return (self._series.get(security_id) or {}).get(day)

    def trading_days(self, security_id: str, *, start: str, end: str) -> list[str]:
        """Return observed trading days in a closed calendar interval."""
        days = self._days.get(security_id) or []
        left = bisect_left(days, start)
        right = bisect_right(days, end)
        return days[left:right]

    def period_return(self, security_id: str, start: str, end: str) -> Decimal | None:
        """区间复权收益，百分比。"""
        first = self.close(security_id, start)
        last = self.close(security_id, end)
        if first is None or last is None or first == 0:
            return None
        return ((last - first) / first * Decimal(100)).quantize(QUANT)

    def unconditional_excess_returns(
        self,
        security_id: str,
        *,
        start: str,
        end: str,
        window_days: int = WINDOW_DAYS,
    ) -> list[Decimal]:
        """Build the same-security unconditional forward-return comparison pool.

        Every trading day in the requested interval is treated as a hypothetical
        disclosure day.  Its window starts on the next trading day, exactly like
        ``build_label``.  Incomplete and missing-price windows are excluded.
        """
        values: list[Decimal] = []
        for day in self.trading_days(security_id, start=start, end=end):
            window_start = self.next_trading_day(security_id, day)
            if window_start is None:
                continue
            window_end = self.forward_day(security_id, window_start, window_days)
            if window_end is None:
                continue
            security_return = self.period_return(security_id, window_start, window_end)
            benchmark_return = self.period_return(BENCHMARK.security_id, window_start, window_end)
            if security_return is None or benchmark_return is None:
                continue
            values.append(excess_return(security_return, benchmark_return))
        return values


def build_label(
    book: QuoteBook,
    *,
    security_id: str,
    disclosure_time: str,
    time_is_precise: bool,
    window_days: int = WINDOW_DAYS,
    as_of: str | None = None,
) -> ReturnLabel:
    """生成一条标签。

    `as_of` 是「现在」，默认取行情最后一个交易日。窗口结束日晚于它就是待观察——
    这是防未来信息泄露的最后一道闸门。
    """
    disclosure_day = disclosure_time[:10]
    reference = as_of or book.last_trading_day

    # 时刻不明确时按盘后处理：起算日推到披露日之后
    window_start = book.next_trading_day(security_id, disclosure_day)
    if window_start is None:
        return ReturnLabel(
            security_id,
            disclosure_time,
            "",
            "",
            None,
            None,
            None,
            "待观察",
            "披露日之后暂无交易日数据",
        )

    window_end = book.forward_day(security_id, window_start, window_days)
    if window_end is None:
        return ReturnLabel(
            security_id,
            disclosure_time,
            window_start,
            "",
            None,
            None,
            None,
            "待观察",
            f"窗口未满 {window_days} 个交易日",
        )

    if window_end > reference:
        return ReturnLabel(
            security_id,
            disclosure_time,
            window_start,
            window_end,
            None,
            None,
            None,
            "待观察",
            f"窗口结束日 {window_end} 晚于数据截止 {reference}",
        )

    security_ret = book.period_return(security_id, window_start, window_end)
    benchmark_ret = book.period_return(BENCHMARK.security_id, window_start, window_end)
    if security_ret is None or benchmark_ret is None:
        return ReturnLabel(
            security_id,
            disclosure_time,
            window_start,
            window_end,
            security_ret,
            benchmark_ret,
            None,
            "待观察",
            "区间内价格数据缺失（可能停牌）",
        )

    return ReturnLabel(
        security_id,
        disclosure_time,
        window_start,
        window_end,
        security_ret,
        benchmark_ret,
        excess_return(security_ret, benchmark_ret),
        "已生成",
    )


def is_hit(direction: str, label: ReturnLabel) -> bool | None:
    """命中判定（说明书 10.3）：正向信号对应正超额，负向对应负超额。

    返回 None 表示无法判定，不算命中也不算未命中——把无法判定的算作未命中会低估，
    算作命中会高估。
    """
    if label.excess_return is None:
        return None
    if direction == "支持":
        return label.excess_return > 0
    if direction in {"削弱", "冲突"}:
        return label.excess_return < 0
    return None
