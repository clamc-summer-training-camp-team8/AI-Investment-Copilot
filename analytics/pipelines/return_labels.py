"""C 类管道：20 日行业中性超额收益标签（指标字典 MET-004）。

四条时间纪律，任何一条破了标签就不可用：

1. **T+1 起算。** 窗口从首次可得时间的**下一个可交易时点**开始。当天披露当天买入
   是拿不到的信息。
2. **窗口结束后才生成标签。** DQ-006 强制 `label_generated_at >= window_end`，
   窗口未结束一律标「待观察」，不用部分窗口的收益凑数。
3. **披露时间无具体时刻的按盘后处理。** 巨潮有 66% 的公告时间是 00:00，无法区分
   盘前盘后。假设盘前（当日可交易）会高估可得性，因此一律当盘后 → 次日起算。
   这个选择使标签更保守，不会因为时点假设制造虚假超额。
4. **基准事前确定，且按行业取。** 三个行业各一个基准（见 universe.BENCHMARKS），
   选定后不换。跨行业共用一个基准算出来的「超额」里混着行业轮动，不是个股 alpha。

超额收益的算法委托给 `app.calc.deterministic.excess_return`，不在这里重写。离线与
线上算出不同数字是最伤信任的问题（analytics/README.md）。
"""

from __future__ import annotations

import json
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from analytics.pipelines.universe import benchmark_for
from app.calc.deterministic import excess_return
from app.core.config import PROJECT_ROOT
from app.core.enums import ImpactDirection

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
        raw_series: dict[str, dict[str, str]] = payload["series"]  # type: ignore[assignment]
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

    def period_return(self, security_id: str, start: str, end: str) -> Decimal | None:
        """区间复权收益，百分比。"""
        first = self.close(security_id, start)
        last = self.close(security_id, end)
        if first is None or last is None or first == 0:
            return None
        return ((last - first) / first * Decimal(100)).quantize(QUANT)


def build_label(
    book: QuoteBook,
    *,
    security_id: str,
    disclosure_time: str,
    window_days: int = WINDOW_DAYS,
    as_of: str | None = None,
) -> ReturnLabel:
    """生成一条标签。

    `as_of` 是「现在」，默认取行情最后一个交易日。窗口结束日晚于它就是待观察——
    这是防未来信息泄露的最后一道闸门。

    起算日一律取披露日之后的第一个交易日（T+1），不区分披露时刻精确与否。
    数据集里 3784 条事件只有 661 条带精确时刻，其中 199 条在收盘前；对这少数
    几条改用 T+0 能多算一天收益，但代价是同一份实验里混进两套起算规则，
    跨行业、跨时段的对照会失去可比性。宁可统一让利一天。

    这里曾有一个 `time_is_precise` 参数，签名收下却从未参与分支判断，
    读代码的人会以为精确时刻走了另一条路径。参数已删除，规则写进注释。
    """
    disclosure_day = disclosure_time[:10]
    reference = as_of or book.last_trading_day

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

    # 基准按行业取。跨行业共用一个基准会把行业轮动算成个股 alpha，
    # 三个行业的涨跌节奏差异远大于单只个股的事件效应。
    benchmark = benchmark_for(security_id)
    security_ret = book.period_return(security_id, window_start, window_end)
    benchmark_ret = book.period_return(benchmark.security_id, window_start, window_end)
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

    方向取值统一用 ``ImpactDirection`` 的枚举值。曾经这里写的是字面量「削弱」，
    而枚举值是「冲突」：「削弱」只是 CSV 导入用的外部别名（见 app/ingest/events.py）。
    结果是 candidate_v2 输出的 19 条冲突信号全部判为无法判定，25 条信号只剩 6 条，
    实验样本量被静默砍掉四分之三，而报告把它归因成「设计使然」。
    """
    if label.excess_return is None:
        return None
    if direction == ImpactDirection.SUPPORT:
        return label.excess_return > 0
    if direction == ImpactDirection.CONFLICT:
        return label.excess_return < 0
    return None
