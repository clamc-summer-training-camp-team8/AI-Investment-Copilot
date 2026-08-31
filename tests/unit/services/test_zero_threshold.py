"""阈值 0 必须被当作阈值，不能被预期值顶替。

真实缺陷：`compute_suggestion` 里写的是 `mapping.invalidation_threshold or
mapping.expected_value`。Decimal("0.00") 为假，于是「营业收入同比转负则失效」
（阈值 0）被静默替换成「同比低于预期值则失效」。北方华创 2026Q1 单季营收同比
+26.3% 与 +25.8%，两期都远高于 0，却因为低于预期值 30% 被判定连续两期突破，
触发重大风险建议。

这类缺陷不会报错、不会抛异常，只会让失效判定变成另一条规则，而报告上仍然写着
「营业收入同比连续 2 个季度转负」。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core.config import RuleThresholds
from app.core.domain import (
    HypothesisRecord,
    MetricMappingRecord,
    ObservationRecord,
    ThesisRecord,
)
from app.core.enums import (
    ExpectationDirection,
    Importance,
    ThesisStatus,
    Visibility,
)
from app.services import status as status_service
from tests.fakes import build_fake_uow

ESTABLISHED = date(2026, 1, 20)


def _setup(observations: list[str]) -> tuple[object, ThesisRecord, list[HypothesisRecord]]:
    uow = build_fake_uow()
    thesis = ThesisRecord(
        thesis_id="THS-ZERO",
        security_id="002371",
        title="阈值 0 回归用例",
        direction="看多",
        core_view="营业收入同比转负则该假设失效",
        established_on=ESTABLISHED,
        owner="analyst",
        status=ThesisStatus.VALIDATING,
        visibility=Visibility.PRIVATE,
        horizon_end_on=date(2026, 4, 30),
        invalidation_require_all=True,
        invalidation_hypotheses=["THS-ZERO-H1"],
    )
    uow.thesis.add(thesis)

    hypothesis = HypothesisRecord(
        hypothesis_id="THS-ZERO-H1",
        thesis_id="THS-ZERO",
        statement="营业收入保持增长",
        hypothesis_type="经营",
        importance=Importance.CORE,
        invalidation_rule="营业收入同比连续 2 个季度转负则该假设失效",
    )
    uow.thesis.add_hypothesis(hypothesis)

    uow.thesis.add_mapping(
        MetricMappingRecord(
            mapping_id="THS-ZERO-H1-map",
            hypothesis_id="THS-ZERO-H1",
            metric_id="MET-001",
            expected_direction=ExpectationDirection.HIGHER_BETTER,
            metric_version="v1.0",
            expected_value=Decimal("30.00"),
            invalidation_threshold=Decimal("0.00"),
            invalidation_consecutive_periods=2,
            expectation_source="测试",
        )
    )

    for index, value in enumerate(observations):
        uow.observations.add(
            ObservationRecord(
                security_id="002371",
                metric_id="MET-001",
                period=f"2026Q{index + 1}",
                observation_date=date(2026, 3, 1 + index),
                unit="%",
                actual_value=Decimal(value),
                metric_version="v1.0",
                period_type="单季度",
                data_version="test",
            )
        )
    return uow, thesis, [hypothesis]


def test_低于预期但为正增长不算失效() -> None:
    """+26% 与 +25% 低于预期 30%，但没有转负，不该触发失效。"""
    uow, thesis, hypotheses = _setup(["26.2914", "25.7961"])
    suggestion = status_service.compute_suggestion(
        uow,
        thesis=thesis,
        hypotheses=hypotheses,
        thresholds=RuleThresholds(),
        today=date(2026, 4, 30),
    )
    assert suggestion.triggered_hypotheses == []
    assert suggestion.suggested_status is not ThesisStatus.MAJOR_RISK


def test_连续两期转负才算失效() -> None:
    """阈值 0 生效时，只有真的转负才触发。"""
    uow, thesis, hypotheses = _setup(["-3.20", "-5.10"])
    suggestion = status_service.compute_suggestion(
        uow,
        thesis=thesis,
        hypotheses=hypotheses,
        thresholds=RuleThresholds(),
        today=date(2026, 4, 30),
    )
    assert "THS-ZERO-H1" in suggestion.triggered_hypotheses


def test_单期转负是关注不是失效() -> None:
    """要求连续 2 期，1 期只进关注，不判失效——避免单季度波动触发误判。

    `triggered_hypotheses` 会同时包含「已突破」与「接近失效」，所以这里断言的是
    状态没有升到重大风险，而不是列表为空。
    """
    uow, thesis, hypotheses = _setup(["5.00", "-5.10"])
    suggestion = status_service.compute_suggestion(
        uow,
        thesis=thesis,
        hypotheses=hypotheses,
        thresholds=RuleThresholds(),
        today=date(2026, 4, 30),
    )
    assert suggestion.suggested_status is not ThesisStatus.MAJOR_RISK
    assert any("接近失效阈值" in reason for reason in suggestion.reasons)


def test_过期指标不能直接触发失效建议() -> None:
    """旧数据即使曾突破阈值，也只能等待补数或人工复核。"""
    uow, thesis, hypotheses = _setup(["-3.20", "-5.10"])
    suggestion = status_service.compute_suggestion(
        uow,
        thesis=thesis,
        hypotheses=hypotheses,
        thresholds=RuleThresholds(metric_max_age_days=30),
        today=date(2026, 8, 30),
    )
    assert suggestion.suggested_status is not ThesisStatus.MAJOR_RISK
    assert suggestion.triggered_hypotheses == []
