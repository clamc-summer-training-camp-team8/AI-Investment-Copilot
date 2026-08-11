"""离线管道里的方向字面量必须与 ImpactDirection 枚举值对齐。

这不是风格检查。曾经 return_labels.is_hit 判的是「削弱」，而枚举值是「冲突」，
「削弱」只是 CSV 导入的外部别名（app/ingest/events.py）。后果是 candidate_v2 输出的
19 条冲突信号全部被判为无法判定，25 条信号只剩 6 条，样本外只剩 2 条，
而验收报告把样本量不足归因成「设计使然」。字面量不一致不会报错，只会让结论失真。
"""

from __future__ import annotations

from decimal import Decimal

from analytics.pipelines.return_labels import ReturnLabel, is_hit
from app.core.enums import ImpactDirection


def _label(excess: str) -> ReturnLabel:
    return ReturnLabel(
        security_id="000000",
        disclosure_time="2025-01-02T09:00:00+08:00",
        window_start="2025-01-03",
        window_end="2025-02-07",
        security_return=Decimal("0"),
        benchmark_return=Decimal("0"),
        excess_return=Decimal(excess),
        status="已生成",
    )


def test_冲突方向能被判定命中() -> None:
    """负向信号遇到负超额算命中。写成别名「削弱」时这里会返回 None。"""
    assert is_hit(ImpactDirection.CONFLICT, _label("-3.5")) is True
    assert is_hit(ImpactDirection.CONFLICT, _label("2.0")) is False


def test_支持方向能被判定命中() -> None:
    assert is_hit(ImpactDirection.SUPPORT, _label("2.0")) is True
    assert is_hit(ImpactDirection.SUPPORT, _label("-2.0")) is False


def test_外部别名不再被当作方向() -> None:
    """「削弱」是导入别名，不是枚举值。管道内部一律用枚举值，别名只在入口转换。"""
    assert is_hit("削弱", _label("-3.5")) is None


def test_无方向不参与命中判定() -> None:
    """中性和无关没有方向，不算命中也不算未命中，否则会系统性偏移命中率。"""
    assert is_hit(ImpactDirection.NEUTRAL, _label("-3.5")) is None
    assert is_hit(ImpactDirection.IRRELEVANT, _label("2.0")) is None


def test_超额缺失时不猜命中() -> None:
    """停牌或窗口未满时超额为空，必须返回无法判定。"""
    label = ReturnLabel(
        security_id="000000",
        disclosure_time="2025-01-02T09:00:00+08:00",
        window_start="",
        window_end="",
        security_return=None,
        benchmark_return=None,
        excess_return=None,
        status="待观察",
    )
    assert is_hit(ImpactDirection.CONFLICT, label) is None


def test_候选抽取只输出枚举值() -> None:
    """candidate_v2 的方向输出必须落在枚举值域内，否则下游过滤会静默丢样本。"""
    from analytics.evaluation.candidate_v2 import predict

    allowed = {m.value for m in ImpactDirection}
    titles = (
        "关于获得药品注册批准的公告",
        "2025年半年度报告",
        "关于签订重大合同的公告",
        "2025年第三季度业绩预告（预减）",
        "关于回购公司股份的进展公告",
    )
    for title in titles:
        assert predict(title).direction in allowed
