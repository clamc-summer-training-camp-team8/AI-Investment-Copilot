"""失效判定的建立日裁剪守门测试。

样例数据里 2025Q2(0.11) 与 2025Q3(0.13) 连续两期低于 0.15 预期，但两期都早于
逻辑建立日 2026-01-15。不裁剪观察窗口的话，导入样例数据的瞬间就会误判 H2 失效，
给研究员发一条错误的重大风险提醒。

这个文件是 app/calc/rules.py 裁剪逻辑的回归保护，改动 check_invalidation 时
必须保证这些断言仍然成立。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.calc.rules import check_invalidation
from app.core.config import RuleThresholds
from app.core.enums import ExpectationDirection
from tests.conftest import make_observation

ESTABLISHED_ON = date(2026, 1, 15)
THRESHOLD = Decimal("0.15")

SAMPLE_HISTORY = [
    make_observation("2025Q2", date(2025, 6, 30), "0.11", expected="0.15"),
    make_observation("2025Q3", date(2025, 9, 30), "0.13", expected="0.15"),
    make_observation("2025Q4", date(2025, 12, 31), "0.16", expected="0.15"),
    make_observation("2026Q1", date(2026, 3, 31), "0.18", expected="0.15"),
]


def test_样例数据不触发失效(thresholds: RuleThresholds) -> None:
    result = check_invalidation(
        "H2",
        SAMPLE_HISTORY,
        thesis_established_on=ESTABLISHED_ON,
        threshold=THRESHOLD,
        direction=ExpectationDirection.HIGHER_BETTER,
        thresholds=thresholds,
    )

    assert result.breached is False
    assert result.excluded_periods == ["2025Q2", "2025Q3", "2025Q4"]
    assert result.evaluated_periods == ["2026Q1"]


def test_不裁剪时的连续突破会被排除掉(thresholds: RuleThresholds) -> None:
    """把建立日提前到样例历史之前，连续两期低于阈值才应触发失效。

    这条断言的作用是证明"未触发"来自窗口裁剪，而不是判定逻辑本身失灵。
    """
    result = check_invalidation(
        "H2",
        SAMPLE_HISTORY[:2],
        thesis_established_on=date(2025, 1, 1),
        threshold=THRESHOLD,
        direction=ExpectationDirection.HIGHER_BETTER,
        thresholds=thresholds,
    )

    assert result.breached is True
    assert result.consecutive_breaches == 2
    assert result.excluded_periods == []


def test_接近阈值但未突破(thresholds: RuleThresholds) -> None:
    """0.16 相对 0.15 的差距为 6.7%，在 near_invalidation_ratio=0.1 之内。"""
    result = check_invalidation(
        "H2",
        [make_observation("2026Q1", date(2026, 3, 31), "0.16", expected="0.15")],
        thesis_established_on=ESTABLISHED_ON,
        threshold=THRESHOLD,
        direction=ExpectationDirection.HIGHER_BETTER,
        thresholds=thresholds,
    )

    assert result.breached is False
    assert result.near_breach is True


def test_单期突破不足以判定失效(thresholds: RuleThresholds) -> None:
    result = check_invalidation(
        "H2",
        [make_observation("2026Q1", date(2026, 3, 31), "0.10", expected="0.15")],
        thesis_established_on=ESTABLISHED_ON,
        threshold=THRESHOLD,
        direction=ExpectationDirection.HIGHER_BETTER,
        thresholds=thresholds,
    )

    assert result.breached is False
    assert result.consecutive_breaches == 1
    assert result.required_consecutive == 2


def test_数据缺失不推算(thresholds: RuleThresholds) -> None:
    """缺失值打断连续计数，不按"缺失即未突破"或"缺失即突破"任一方向猜测。"""
    result = check_invalidation(
        "H2",
        [
            make_observation("2026Q1", date(2026, 3, 31), "0.10", expected="0.15"),
            make_observation("2026Q2", date(2026, 6, 30), None, expected="0.15"),
            make_observation("2026Q3", date(2026, 9, 30), "0.10", expected="0.15"),
        ],
        thesis_established_on=ESTABLISHED_ON,
        threshold=THRESHOLD,
        direction=ExpectationDirection.HIGHER_BETTER,
        thresholds=thresholds,
    )

    assert result.breached is False
    assert result.consecutive_breaches == 1
