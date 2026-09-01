from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.calc.deterministic import Observation
from app.calc.rules import check_invalidation_range
from app.core.config import RuleThresholds


def _observation(period: str, value: str) -> Observation:
    return Observation(
        metric_id="MET-RANGE",
        period=period,
        observation_date=date.fromisoformat(f"2026-{period}-01"),
        actual_value=Decimal(value),
        unit="%",
        period_type="月值",
    )


def test_rising_metric_below_lower_bound_triggers_review_after_two_periods() -> None:
    result = check_invalidation_range(
        "H1",
        [_observation("01", "11"), _observation("02", "9"), _observation("03", "8")],
        thesis_established_on=date(2026, 1, 1),
        lower=Decimal("10"),
        upper=None,
        thresholds=RuleThresholds(),
        required_consecutive=2,
    )

    assert result.breached is True
    assert result.consecutive_breaches == 2
    assert "仅生成复核提醒" in result.note


def test_fluctuating_metric_inside_bounds_does_not_trigger_review() -> None:
    result = check_invalidation_range(
        "H2",
        [_observation("01", "10"), _observation("02", "12"), _observation("03", "11")],
        thesis_established_on=date(2026, 1, 1),
        lower=Decimal("8"),
        upper=Decimal("13"),
        thresholds=RuleThresholds(),
        required_consecutive=1,
    )

    assert result.breached is False
    assert result.consecutive_breaches == 0
