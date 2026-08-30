"""只读查询接口的边界。

守三件事：
1. 列表按可见性过滤——列表接口不走 `_require_visible`，过滤是它唯一的守卫，
   所以这条测试是 test_permission_boundaries 里豁免 list_theses 的前提。
2. 分页有上限且不接受负偏移。
3. 趋势带口径字段，且不把逻辑成立日之前的观测算进来。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.domain import (
    HypothesisRecord,
    MetricMappingRecord,
    ObservationRecord,
    ThesisQuery,
    ThesisRecord,
)
from app.core.enums import (
    ConfirmationStatus,
    ExpectationDirection,
    Importance,
    ThesisStatus,
    Visibility,
)
from app.services import query as query_service
from app.services.permission import Actor
from tests.fakes import build_fake_uow

OWNER = "研究员A"
ESTABLISHED = date(2025, 1, 20)


def _thesis(
    thesis_id: str, *, owner: str = OWNER, visibility: str = Visibility.PRIVATE
) -> ThesisRecord:
    return ThesisRecord(
        thesis_id=thesis_id,
        security_id="688981",
        title=f"{thesis_id} 观察",
        direction="观察",
        core_view="成熟制程产能利用率回升",
        established_on=ESTABLISHED,
        owner=owner,
        status=ThesisStatus.VALIDATING,
        visibility=visibility,
    )


def test_列表按可见性过滤掉他人私有卡片() -> None:
    """这条是 list_theses 豁免 _require_visible 的前提。

    列表不做单卡校验，过滤是它唯一的守卫；这里失败意味着接口会把别人的私有
    研究覆盖泄露出去。
    """
    uow = build_fake_uow()
    uow.thesis.add(_thesis("THS-MINE"))
    uow.thesis.add(_thesis("THS-OTHER", owner="研究员B"))

    page = query_service.list_theses(uow, Actor(user_id=OWNER), ThesisQuery())

    assert [r.thesis_id for r in page.items] == ["THS-MINE"]


def test_团队可见对同队可见对外队不可见() -> None:
    uow = build_fake_uow()
    record = _thesis("THS-TEAM", owner="研究员B", visibility=Visibility.TEAM)
    record.team = "权益研究"
    uow.thesis.add(record)

    teammate = Actor(user_id=OWNER, teams=frozenset({"权益研究"}))
    outsider = Actor(user_id=OWNER, teams=frozenset({"固收研究"}))

    assert query_service.list_theses(uow, teammate, ThesisQuery()).items
    assert not query_service.list_theses(uow, outsider, ThesisQuery()).items


@pytest.mark.parametrize(
    ("requested", "expected"),
    [(0, 1), (-5, 1), (20, 20), (query_service.MAX_LIMIT + 100, query_service.MAX_LIMIT)],
)
def test_分页上限被夹住(requested: int, expected: int) -> None:
    """列表接口禁止无上限查询。0 与负数夹到 1 而不是报错，也不是返回全表。"""
    assert query_service.clamp_limit(requested) == expected


def test_负偏移当成零() -> None:
    uow = build_fake_uow()
    uow.thesis.add(_thesis("THS-1"))
    page = query_service.list_theses(uow, Actor(user_id=OWNER), ThesisQuery(offset=-10))
    assert page.offset == 0
    assert len(page.items) == 1


def test_总数是过滤前候选数而非当页条数() -> None:
    """total 用于渲染页码，必须是候选总数。"""
    uow = build_fake_uow()
    for i in range(5):
        uow.thesis.add(_thesis(f"THS-{i}"))

    page = query_service.list_theses(uow, Actor(user_id=OWNER), ThesisQuery(limit=2))

    assert page.total == 5
    assert len(page.items) == 2


def _seed_trend(uow, *, include_before: bool) -> ThesisRecord:
    thesis = _thesis("THS-TREND")
    uow.thesis.add(thesis)
    uow.thesis.add_hypothesis(
        HypothesisRecord(
            hypothesis_id="H2-盈利质量",
            thesis_id=thesis.thesis_id,
            statement="毛利率随产能利用率回升",
            hypothesis_type="盈利",
            importance=Importance.CORE,
        )
    )
    uow.thesis.add_mapping(
        MetricMappingRecord(
            mapping_id="MAP-1",
            hypothesis_id="H2-盈利质量",
            metric_id="MET-002",
            expected_direction=ExpectationDirection.HIGHER_BETTER,
            expected_value=Decimal("22.00"),
            invalidation_threshold=Decimal("18.50"),
            expectation_source="2022Q1~2024Q3 单季度 25 分位",
            confirmation_status=ConfirmationStatus.CONFIRMED,
        )
    )

    periods = [
        ("2024Q1", date(2024, 5, 9), "14.19"),  # 早于建立日
        ("2025Q1", date(2025, 5, 8), "23.10"),
        ("2025Q2", date(2025, 8, 29), "20.70"),
        ("2025Q3", date(2025, 11, 14), "25.49"),
        ("2025Q4", date(2026, 3, 27), "17.38"),
    ]
    for period, available_on, value in periods:
        if not include_before and available_on < thesis.established_on:
            continue
        uow.observations.add(
            ObservationRecord(
                security_id=thesis.security_id,
                metric_id="MET-002",
                period=period,
                observation_date=available_on,
                unit="%",
                actual_value=Decimal(value),
                metric_version="v1.0",
                period_type="单季度",
                data_version="em-f10-gincome-v2",
            )
        )
    return thesis


def test_趋势排除逻辑成立日之前的观测() -> None:
    """不裁剪窗口会把逻辑成立之前的历史算成对它的验证。"""
    uow = build_fake_uow()
    thesis = _seed_trend(uow, include_before=True)

    trends = query_service.hypothesis_trends(uow, thesis)

    assert len(trends) == 1
    result = trends[0].result
    assert result is not None
    assert "2024Q1" not in result.periods
    assert "已排除" in trends[0].note


def test_趋势必带口径字段() -> None:
    """FR-V-001：只给一串数字前端无法展示口径与来源。"""
    uow = build_fake_uow()
    thesis = _seed_trend(uow, include_before=False)

    trend_view = query_service.hypothesis_trends(uow, thesis)[0]

    assert trend_view.unit == "%"
    assert trend_view.period_type == "单季度"
    assert trend_view.metric_version == "v1.0"
    assert trend_view.data_version == "em-f10-gincome-v2"


def test_一个假设的全部指标映射都返回趋势() -> None:
    """多指标是假设的一等关系，不能只展示排序后的第一条。"""
    uow = build_fake_uow()
    thesis = _seed_trend(uow, include_before=False)
    uow.thesis.add_mapping(
        MetricMappingRecord(
            mapping_id="MAP-2",
            hypothesis_id="H2-盈利质量",
            metric_id="MET-001",
            expected_direction=ExpectationDirection.HIGHER_BETTER,
            expected_value=Decimal("10"),
            expectation_source="研究员人工确认",
            confirmation_status=ConfirmationStatus.CONFIRMED,
        )
    )
    uow.observations.add(
        ObservationRecord(
            security_id=thesis.security_id,
            metric_id="MET-001",
            period="2025Q4",
            observation_date=date(2026, 3, 27),
            unit="%",
            actual_value=Decimal("12"),
            data_version="em-f10-gincome-v2",
        )
    )

    trends = query_service.hypothesis_trends(uow, thesis)

    assert {item.metric_id for item in trends} == {"MET-001", "MET-002"}


def test_无指标映射的假设也返回一行() -> None:
    """H3 产能与扩张没有量化指标，静默跳过会让界面少一条假设。"""
    uow = build_fake_uow()
    thesis = _thesis("THS-NO-MAP")
    uow.thesis.add(thesis)
    uow.thesis.add_hypothesis(
        HypothesisRecord(
            hypothesis_id="H3-产能与扩张",
            thesis_id=thesis.thesis_id,
            statement="资本开支与扩产节奏匹配下游需求",
            hypothesis_type="产能",
            importance=Importance.SUPPORTING,
        )
    )

    trends = query_service.hypothesis_trends(uow, thesis)

    assert len(trends) == 1
    assert trends[0].result is None
    assert "人工判断" in trends[0].note
