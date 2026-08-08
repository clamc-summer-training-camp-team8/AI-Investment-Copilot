"""确定性计算的口径与精度约束。

对应 DA-AC-04：预期差、同比/环比、趋势和简单同业比较可复核。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.calc.deterministic import (
    CalibrationConflictError,
    excess_return,
    expectation_gap,
    trend,
)
from app.core.enums import ExpectationDirection, ValidationVerdict
from tests.conftest import make_observation


def test_超额收益无浮点残留() -> None:
    """样例台账里 -0.02 曾被存成 -0.019999999999999997，不能出现在研究员屏幕上。"""
    assert excess_return("0.08", "0.10") == Decimal("-0.020000")


def test_预期差同时给出绝对差与相对差() -> None:
    obs = make_observation("2026Q1", date(2026, 3, 31), "0.18", expected="0.15")
    gap = expectation_gap(obs, direction=ExpectationDirection.HIGHER_BETTER)

    assert gap.absolute_gap == Decimal("0.030000")
    assert gap.relative_gap == Decimal("0.200000")
    assert gap.verdict is ValidationVerdict.SUPPORT


def test_预期值缺失时返回信息不足而不推算() -> None:
    obs = make_observation("2026Q1", date(2026, 3, 31), "0.18", expected=None)
    gap = expectation_gap(obs)

    assert gap.verdict is ValidationVerdict.INSUFFICIENT
    assert gap.absolute_gap is None


def test_单位不一致禁止比较() -> None:
    observations = [
        make_observation("2026Q1", date(2026, 3, 31), "0.18", unit="%"),
        make_observation("2026Q2", date(2026, 6, 30), "1.80", unit="亿元"),
    ]
    with pytest.raises(CalibrationConflictError):
        trend(observations, min_periods=2)


def test_报告期口径不一致禁止混算() -> None:
    observations = [
        make_observation("2026Q1", date(2026, 3, 31), "0.18", period_type="单季度"),
        make_observation("2026H1", date(2026, 6, 30), "0.35", period_type="累计"),
    ]
    with pytest.raises(CalibrationConflictError):
        trend(observations, min_periods=2)


def test_指标口径版本不一致禁止比较() -> None:
    observations = [
        make_observation("2026Q1", date(2026, 3, 31), "0.18", metric_version="v1.0"),
        make_observation("2026Q2", date(2026, 6, 30), "0.19", metric_version="v2.0"),
    ]
    with pytest.raises(CalibrationConflictError):
        trend(observations, min_periods=2)


def test_趋势期数不足时返回信息不足() -> None:
    """FR-V-002 要求最近 4 至 8 期，不足 4 期不给方向结论。"""
    observations = [
        make_observation("2026Q1", date(2026, 3, 31), "0.18"),
        make_observation("2026Q2", date(2026, 6, 30), "0.19"),
    ]
    result = trend(observations, min_periods=4)

    assert result.verdict is ValidationVerdict.INSUFFICIENT
    assert result.direction == "信息不足"
    assert result.slope is None


def test_趋势只取最近若干期() -> None:
    observations = [
        make_observation(f"P{i}", date(2024 + i // 4, (i % 4) * 3 + 1, 1), f"0.1{i}")
        for i in range(10)
    ]
    result = trend(observations, min_periods=4, max_periods=8)

    assert len(result.periods) == 8
    assert result.direction == "上升"
