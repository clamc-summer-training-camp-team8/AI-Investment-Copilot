"""thesis 级组合失效条件。

样例案例（标注规范 §6）的失效条件是「海外收入连续两个季度低于预期 **且**
毛利率低于 18%」。2026Q1 实际情况是收入 0.18 ≥ 0.15 达标、毛利率 0.17 < 0.18
不达标，AND 条件不成立，正确结论是「风险关注」而不是「失效」。

把 AND 误当 OR 的后果是单个指标不达标就判整条逻辑失效。误报会让研究员停止信任
提醒，这比漏报更伤产品。这个文件锁住这条边界。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.calc.rules import (
    InvalidationCheck,
    ThesisInvalidation,
    check_invalidation,
    evaluate_thesis_invalidation,
    suggest_status,
)
from app.core.config import RuleThresholds
from app.core.enums import ExpectationDirection, ThesisStatus
from tests.conftest import make_observation

ESTABLISHED_ON = date(2026, 1, 15)


def _revenue_check(thresholds: RuleThresholds) -> InvalidationCheck:
    """H2 海外收入同比：预期 15%，要求连续两期低于预期才算突破。"""
    return check_invalidation(
        "HYP-DEMO-002",
        [
            make_observation("2025Q4", date(2025, 12, 31), "0.16", expected="0.15"),
            make_observation("2026Q1", date(2026, 3, 31), "0.18", expected="0.15"),
        ],
        thesis_established_on=ESTABLISHED_ON,
        threshold=Decimal("0.15"),
        direction=ExpectationDirection.HIGHER_BETTER,
        thresholds=thresholds,
        required_consecutive=2,
    )


def _margin_check(thresholds: RuleThresholds) -> InvalidationCheck:
    """H3 海外项目毛利率：阈值 18%，单期低于即标记风险。"""
    return check_invalidation(
        "HYP-DEMO-003",
        [make_observation("2026Q1", date(2026, 3, 31), "0.17", expected="0.18", unit="%")],
        thesis_established_on=ESTABLISHED_ON,
        threshold=Decimal("0.18"),
        direction=ExpectationDirection.NOT_BELOW_THRESHOLD,
        thresholds=thresholds,
        required_consecutive=1,
    )


def test_样例案例仅毛利率不达标时不判定失效(thresholds: RuleThresholds) -> None:
    """标注规范 §6 的人工判断答案：未满足全部条件，改为风险关注。"""
    revenue = _revenue_check(thresholds)
    margin = _margin_check(thresholds)

    assert revenue.breached is False
    assert margin.breached is True

    verdict = evaluate_thesis_invalidation("THS-DEMO-001", [revenue, margin], require_all=True)

    assert verdict.satisfied is False
    assert verdict.breached_hypotheses == ["HYP-DEMO-003"]
    assert verdict.unmet_hypotheses == ["HYP-DEMO-002"]


def test_组合条件未成立时不建议重大风险(thresholds: RuleThresholds) -> None:
    """核心断言：单条假设已突破，但 AND 条件不成立，状态维持验证中。"""
    margin = _margin_check(thresholds)
    verdict = evaluate_thesis_invalidation(
        "THS-DEMO-001",
        [_revenue_check(thresholds), margin],
        require_all=True,
    )

    suggestion = suggest_status(
        ThesisStatus.VALIDATING,
        [],
        [_revenue_check(thresholds), margin],
        thresholds=thresholds,
        thesis_invalidation=verdict,
    )

    assert suggestion.suggested_status is ThesisStatus.VALIDATING
    assert "HYP-DEMO-003" in suggestion.triggered_hypotheses
    assert any("不判定失效" in r for r in suggestion.reasons)
    assert suggestion.output_type == "研究提醒"
    assert suggestion.requires_human_confirmation is False


def test_全部条件成立才建议重大风险(thresholds: RuleThresholds) -> None:
    """收入也连续两期低于预期时，AND 成立，此时应当建议失效。"""
    revenue_breach = check_invalidation(
        "HYP-DEMO-002",
        [
            make_observation("2026Q1", date(2026, 3, 31), "0.10", expected="0.15"),
            make_observation("2026Q2", date(2026, 6, 30), "0.09", expected="0.15"),
        ],
        thesis_established_on=ESTABLISHED_ON,
        threshold=Decimal("0.15"),
        direction=ExpectationDirection.HIGHER_BETTER,
        thresholds=thresholds,
        required_consecutive=2,
    )
    checks = [revenue_breach, _margin_check(thresholds)]
    verdict = evaluate_thesis_invalidation("THS-DEMO-001", checks, require_all=True)

    assert verdict.satisfied is True
    assert verdict.unmet_hypotheses == []

    suggestion = suggest_status(
        ThesisStatus.VALIDATING,
        [],
        checks,
        thresholds=thresholds,
        thesis_invalidation=verdict,
    )
    assert suggestion.suggested_status is ThesisStatus.MAJOR_RISK


def test_任一满足型失效条件(thresholds: RuleThresholds) -> None:
    checks = [_revenue_check(thresholds), _margin_check(thresholds)]
    verdict = evaluate_thesis_invalidation("THS-DEMO-001", checks, require_all=False)

    assert verdict.satisfied is True
    assert verdict.breached_hypotheses == ["HYP-DEMO-003"]


def test_未配置失效条件时不判定失效() -> None:
    """空条件不等于条件成立。"""
    verdict = evaluate_thesis_invalidation("THS-DEMO-001", [], require_all=True)

    assert verdict.satisfied is False
    assert "不判定失效" in verdict.note


def test_条件缺少可判定数据时不算成立(thresholds: RuleThresholds) -> None:
    """参与假设没有对应 check 时按「无法判定」处理，不能退化成少判一条。

    「收入连续两期低于预期 且 毛利率低于 18%」在毛利率还没有观测值时，如果只
    拿收入一条去求 AND，就会凭一个条件报失效——这正是最该避免的误报。
    """
    revenue_breach = check_invalidation(
        "HYP-DEMO-002",
        [
            make_observation("2026Q1", date(2026, 3, 31), "0.10", expected="0.15"),
            make_observation("2026Q2", date(2026, 6, 30), "0.09", expected="0.15"),
        ],
        thesis_established_on=ESTABLISHED_ON,
        threshold=Decimal("0.15"),
        direction=ExpectationDirection.HIGHER_BETTER,
        thresholds=thresholds,
        required_consecutive=2,
    )

    verdict = evaluate_thesis_invalidation(
        "THS-DEMO-001",
        [revenue_breach],
        require_all=True,
        participating=["HYP-DEMO-002", "HYP-DEMO-003"],
    )

    assert verdict.satisfied is False, "毛利率无数据时不得仅凭收入判定失效"
    assert "HYP-DEMO-003" in verdict.unmet_hypotheses
    assert "缺少可判定数据" in verdict.note


def test_条件齐备且全部突破才成立(thresholds: RuleThresholds) -> None:
    """补上第二个条件的数据后，AND 成立。证明上一条拦的是缺数据而非别的分支。"""
    revenue_breach = check_invalidation(
        "HYP-DEMO-002",
        [
            make_observation("2026Q1", date(2026, 3, 31), "0.10", expected="0.15"),
            make_observation("2026Q2", date(2026, 6, 30), "0.09", expected="0.15"),
        ],
        thesis_established_on=ESTABLISHED_ON,
        threshold=Decimal("0.15"),
        direction=ExpectationDirection.HIGHER_BETTER,
        thresholds=thresholds,
        required_consecutive=2,
    )
    verdict = evaluate_thesis_invalidation(
        "THS-DEMO-001",
        [revenue_breach, _margin_check(thresholds)],
        require_all=True,
        participating=["HYP-DEMO-002", "HYP-DEMO-003"],
    )
    assert verdict.satisfied is True


def test_没有组合条件时退回任一突破即建议(thresholds: RuleThresholds) -> None:
    """不传 thesis_invalidation 时保持原行为，避免破坏既有调用方。"""
    suggestion = suggest_status(
        ThesisStatus.VALIDATING,
        [],
        [_margin_check(thresholds)],
        thresholds=thresholds,
    )
    assert suggestion.suggested_status is ThesisStatus.MAJOR_RISK


@pytest.mark.parametrize("required", [1, 2, 3])
def test_每映射可覆盖连续期数(thresholds: RuleThresholds, required: int) -> None:
    """H3 是单期即风险，H1/H2 要连续两期。全局默认值不足以表达。"""
    result = check_invalidation(
        "H",
        [
            make_observation("2026Q1", date(2026, 3, 31), "0.10", expected="0.15"),
            make_observation("2026Q2", date(2026, 6, 30), "0.09", expected="0.15"),
        ],
        thesis_established_on=ESTABLISHED_ON,
        threshold=Decimal("0.15"),
        direction=ExpectationDirection.HIGHER_BETTER,
        thresholds=thresholds,
        required_consecutive=required,
    )

    assert result.required_consecutive == required
    assert result.breached is (required <= 2)


def test_组合结论带可读说明(thresholds: RuleThresholds) -> None:
    """研究员要能看懂为什么没判失效，note 不能为空。"""
    verdict: ThesisInvalidation = evaluate_thesis_invalidation(
        "THS-DEMO-001",
        [_revenue_check(thresholds), _margin_check(thresholds)],
        require_all=True,
    )
    assert verdict.note
    assert "HYP-DEMO-002" in verdict.note
