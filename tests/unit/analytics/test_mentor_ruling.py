from __future__ import annotations

import pytest

from analytics.pipelines.annotate_events import (
    H1,
    H2,
    H3,
    RULING_VERSION,
    annotate_by_action,
    annotate_by_category,
    mentor_ruling,
)
from app.core.enums import ImpactDirection


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("关于获得药物临床试验批准通知书的公告", ("", "无关")),
        ("某产品拟纳入突破性治疗品种公示名单", ("", "无关")),
        ("药品上市许可申请获得受理", (H1, "中性")),
        ("获得创新药药品注册证书", (H1, "支持")),
        ("撤回药品注册申请的公告", (H1, "冲突")),
        ("产品进入国家医保目录", (H1, "支持")),
        ("产品集采中选结果公告", (H2, "中性")),
        ("产品在本轮集采中未中选", (H2, "冲突")),
        ("发行股份购买资产暨关联交易预案", (H3, "中性")),
        ("关于发行中期票据的公告", (H3, "中性")),
        ("签订战略合作框架协议", ("", "无关")),
        ("签订金额10亿元战略合作协议", (H1, "支持")),
        ("III期临床试验达到主要终点", (H1, "支持")),
        ("III期临床试验未达主要终点", (H1, "冲突")),
    ],
)
def test_mentor_ruling_covers_adjudicated_event_types(
    title: str, expected: tuple[str, str]
) -> None:
    assert mentor_ruling(title) == expected


def test_financing_procedural_document_is_irrelevant_before_main_event() -> None:
    title = "独立董事关于发行股份购买资产事项的独立意见"

    assert mentor_ruling(title) == ("", ImpactDirection.IRRELEVANT.value)


def test_ruling_is_applied_to_both_pre_annotators() -> None:
    title = "关于获得药物临床试验批准通知书的公告"

    assert annotate_by_category(title, "其他") == ("", "无关")
    assert annotate_by_action(title, "其他") == ("", "无关")
    assert RULING_VERSION == "mentor-ruling-v1-20260811"
