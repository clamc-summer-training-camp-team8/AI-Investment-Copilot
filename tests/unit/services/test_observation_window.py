"""观察值时间窗口的上界裁剪（DQ-003 未来信息泄露）。

`check_invalidation` 只裁剪逻辑成立日之前的观察值（下界）。上界必须由
`compute_suggestion` 按 `today` 裁掉，否则用历史时点复算状态时会看到未来的财报。

这个缺陷在行业级闭环回归里暴露：2024Q1 建立的逻辑读到了 2026 年的同比数据，
30 条逻辑全部给出相同的失效判断。回溯、复算、样本外实验都依赖这个裁剪。
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

THRESHOLDS = RuleThresholds()


def _setup():
    uow = build_fake_uow()
    thesis = ThesisRecord(
        thesis_id="THS-WIN",
        security_id="300274",
        title="窗口上界裁剪",
        direction="看多",
        core_view="用于验证未来观察值不参与判断",
        established_on=date(2024, 1, 15),
        owner="analyst",
        status=ThesisStatus.VALIDATING,
        visibility=Visibility.PRIVATE,
        version=1,
        invalidation_require_all=False,
        invalidation_hypotheses=["H1"],
    )
    uow.thesis.add(thesis)

    hypothesis = HypothesisRecord(
        hypothesis_id="H1",
        thesis_id=thesis.thesis_id,
        statement="收入同比保持正增长",
        hypothesis_type="经营",
        importance=Importance.CORE,
        invalidation_rule="连续 2 期同比转负则失效",
    )
    uow.thesis.add_hypothesis(hypothesis)
    uow.thesis.add_mapping(
        MetricMappingRecord(
            mapping_id="H1-map",
            hypothesis_id="H1",
            metric_id="MET-001",
            expected_direction=ExpectationDirection.HIGHER_BETTER,
            metric_version="v1.0",
            expected_value=Decimal("20"),
            invalidation_threshold=Decimal("0"),
            invalidation_consecutive_periods=2,
            expectation_source="测试",
        )
    )

    # 近端两期明显为正（远离阈值 0，避免触发接近失效而混淆判断），
    # 远端两期为负。若上界不裁剪，站在 2024 年也会看到 2026 年的负增长。
    for period, day, value in (
        ("2024Q1", date(2024, 4, 30), "25.40"),
        ("2024Q2", date(2024, 8, 31), "14.74"),
        ("2025Q4", date(2026, 4, 30), "-18.37"),
        ("2026Q1", date(2026, 4, 30), "-18.26"),
    ):
        uow.observations.add(
            ObservationRecord(
                security_id="300274",
                metric_id="MET-001",
                period=period,
                observation_date=day,
                unit="%",
                actual_value=Decimal(value),
                metric_version="v1.0",
                period_type="单季度",
            )
        )
    return uow, thesis, [hypothesis]


def test_future_observations_excluded_at_historical_date() -> None:
    """站在 2024-04-30 复算：2026 年的负增长不得参与判断。"""
    uow, thesis, hypotheses = _setup()

    suggestion = status_service.compute_suggestion(
        uow,
        thesis=thesis,
        hypotheses=hypotheses,
        thresholds=THRESHOLDS,
        today=date(2024, 4, 30),
    )

    assert suggestion.suggested_status is ThesisStatus.VALIDATING
    assert not suggestion.triggered_hypotheses, (
        "站在 2024-04-30 不应看到 2026 年的观察值，" f"实际触发了 {suggestion.triggered_hypotheses}"
    )


def test_future_observations_included_when_available() -> None:
    """站在 2026-06-30 复算：两期负增长可得，应触发失效判断。"""
    uow, thesis, hypotheses = _setup()

    suggestion = status_service.compute_suggestion(
        uow,
        thesis=thesis,
        hypotheses=hypotheses,
        thresholds=THRESHOLDS,
        today=date(2026, 6, 30),
    )

    assert suggestion.triggered_hypotheses == ["H1"]
    assert suggestion.suggested_status is ThesisStatus.MAJOR_RISK


def test_today_none_keeps_all_observations() -> None:
    """不传 today 时保持原行为，全部观察值参与——线上按当天跑的路径不受影响。"""
    uow, thesis, hypotheses = _setup()

    suggestion = status_service.compute_suggestion(
        uow, thesis=thesis, hypotheses=hypotheses, thresholds=THRESHOLDS
    )

    assert suggestion.triggered_hypotheses == ["H1"]
