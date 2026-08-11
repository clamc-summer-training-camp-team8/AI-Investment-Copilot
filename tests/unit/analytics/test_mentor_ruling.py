"""导师裁决规则的回归测试。

裁决书：docs/collaboration/20260811-导师裁决-事件方向标注规则.md

这些断言保护的是**业务判定**，不是实现细节。改动 MENTOR_RULINGS 让本文件失败时，
正确的做法是先更新裁决书并递增 RULING_VERSION，而不是改断言——裁决是业务方的
判断，代码不能单方面推翻它。

重点覆盖两类容易回退的问题：

1. **规则顺序**。「撤回药品注册申请」含「注册」、「上市许可申请获受理并纳入优先
   审评程序」含「优先审评」，顺序写错会让具体规则被通用规则吞掉。这两条实测都
   发生过（R4 曾误吞 5 条 NDA 受理）。
2. **过度捕获**。R10 的程序性文件词表曾把「股票交易异常波动问询函回复」和
   「收购报告书」一并判为无关——前者是风险事件，后者是资产交易，都不该被
   募资合规规则捕获。
"""

from __future__ import annotations

import pytest

from analytics.pipelines.annotate_events import (
    annotate_by_action,
    annotate_by_category,
    apply_ruling,
    classify_category,
)
from app.core.enums import ImpactDirection


@pytest.mark.parametrize(
    ("title", "rule", "direction"),
    [
        # R1 临床批件：队列里 213 条，占分歧的 45%。样本内置换检验 p=0.554，
        # 与「随便哪天买恒瑞」无法区分；20 日窗口覆盖 97.7% 的交易日。
        (
            "恒瑞医药关于获得药物临床试验批准通知书的公告",
            "R1",
            ImpactDirection.IRRELEVANT.value,
        ),
        (
            "恒瑞医药关于子公司获得药物临床试验批准通知书的公告",
            "R1",
            ImpactDirection.IRRELEVANT.value,
        ),
        # R2 突破性治疗：含「拟纳入」公示与正式纳入，两种措辞都要覆盖。
        ("恒瑞医药关于药物纳入突破性治疗品种名单的公告", "R2", ImpactDirection.IRRELEVANT.value),
        (
            "恒瑞医药关于子公司药物拟纳入突破性治疗品种名单公示的公告",
            "R2",
            ImpactDirection.IRRELEVANT.value,
        ),
        # R3 资格认定不改变审批结果本身
        (
            "恒瑞医药关于公司药物获得美国FDA快速通道资格的公告",
            "R3",
            ImpactDirection.IRRELEVANT.value,
        ),
        ("恒瑞医药关于获得美国FDA孤儿药资格认定的公告", "R3", ImpactDirection.IRRELEVANT.value),
        # R6 获批上市：研发链上唯一改变当期收入的节点
        ("恒瑞医药关于获得药品注册证书的公告", "R6", ImpactDirection.SUPPORT.value),
        ("恒瑞医药关于获得药品注册批准的公告", "R6", ImpactDirection.SUPPORT.value),
        # R7 撤回：管线归零，是结果
        ("恒瑞医药关于撤回药品注册申请的公告", "R7", ImpactDirection.CONFLICT.value),
        # R5 NDA 受理：审批时钟起点，对当期无方向
        (
            "恒瑞医药关于药品上市许可申请获受理的提示性公告",
            "R5",
            ImpactDirection.NEUTRAL.value,
        ),
    ],
)
def test_医药研发链裁定(title: str, rule: str, direction: str) -> None:
    ruling = apply_ruling(title)
    assert ruling is not None, f"未命中任何裁决规则：{title}"
    assert ruling[0] == rule
    assert ruling[2] == direction


def test_优先审评不得吞掉NDA受理() -> None:
    """R4 必须用「拟纳入」限定，否则会抢走 R5 的样本。

    「上市许可申请获受理并纳入优先审评程序」是一次 NDA 受理，应判中性并留在
    证据链里等审批结果；被 R4 判为无关会让这条证据彻底消失。实测误吞 5 条。
    """
    ruling = apply_ruling("恒瑞医药关于药品上市许可申请获受理并纳入优先审评程序的提示性公告")
    assert ruling is not None
    assert ruling[0] == "R5"
    assert ruling[2] == ImpactDirection.NEUTRAL.value

    # 单纯的优先审评认定仍归 R4
    plain = apply_ruling("恒瑞医药关于药物拟纳入优先审评程序的公告")
    assert plain is not None
    assert plain[0] == "R4"


def test_撤回优先于注册批准() -> None:
    """「撤回药品注册申请」含「注册」二字，R7 必须排在 R6 之前。

    顺序写反会把一条管线归零的坏消息判成「支持」，这是方向完全相反的错误。
    """
    ruling = apply_ruling("恒瑞医药关于撤回药品注册申请的公告")
    assert ruling is not None
    assert ruling[0] == "R7"
    assert ruling[2] == ImpactDirection.CONFLICT.value


def test_股价异动问询函不属于募资程序文件() -> None:
    """R10 的词表不能捕获交易所对股价异动发出的问询函。

    异动问询是风险事件（H2 冲突方向的候选），把它判为无关等于把风险信号删掉。
    实测曾误吞药明康德的股票交易异常波动问询函回复。
    """
    title = "关于对无锡药明康德新药开发股份有限公司股票交易异常波动问询函的回复"
    assert apply_ruling(title) is None
    assert classify_category(title) == "风险与异动"


def test_收购报告书不属于募资程序文件() -> None:
    """「收购报告书」含「报告书」，但它是资产交易文件，不是募资合规文件。

    应由 R14 判中性进人工队列（标的与对价决定方向），而不是被 R10 判无关。
    """
    ruling = apply_ruling("收购报告书摘要")
    assert ruling is not None
    assert ruling[0] == "R14"
    assert ruling[2] == ImpactDirection.NEUTRAL.value


def test_无金额框架协议判无关() -> None:
    """框架协议不含对价、不含交付时点、不构成履约义务，不是订单。

    原规则判「支持」，全样本 6 条命中 1/6、均值超额 −15.31%——小鹏与大众的
    合作公告连续误报。业务口径：没有金额的合作公告不是订单。
    """
    for title in (
        "持续关连交易 与广东汇天签订合作框架协议",
        "自愿公告 与大众汽车集团签订战略技术合作联合开发协议及订立联合采购计划",
    ):
        ruling = apply_ruling(title)
        assert ruling is not None, title
        assert ruling[0] == "R15"
        assert ruling[2] == ImpactDirection.IRRELEVANT.value


def test_发股购买资产判中性而非支持() -> None:
    """资产注入的方向取决于标的质量与对价，标题读不出来。

    原规则判支持，样本内 5 条全部命中、均值 +10.00%，但那是同一天同一起收购的
    7 份文件——一个事件计了 7 次（伪重复），不是 7 条独立证据。
    """
    ruling = apply_ruling("中芯国际关于发行股份购买资产暨关联交易事项的进展公告")
    assert ruling is not None
    assert ruling[0] == "R12"
    assert ruling[2] == ImpactDirection.NEUTRAL.value


@pytest.mark.parametrize(
    "title",
    [
        "恒瑞医药关于获得药物临床试验批准通知书的公告",
        "恒瑞医药关于药物纳入突破性治疗品种名单的公告",
        "兆易创新关于使用闲置募集资金进行现金管理的公告",
        "持续关连交易 与广东汇天签订合作框架协议",
    ],
)
def test_裁决对两名标注者同时生效(title: str) -> None:
    """裁决是业务判定，不是第三个标注者的立场。

    A 判「支持」、B 判「中性」这类分歧已被判定为「两人都不对」，因此裁决必须
    覆盖双方。只对一方生效会制造新的分歧，队列永远清不空。
    """
    category = classify_category(title)
    a_hypothesis, a_direction = annotate_by_category(title, category)
    b_hypothesis, b_direction = annotate_by_action(title, category)

    assert (a_hypothesis, a_direction) == (b_hypothesis, b_direction)

    ruling = apply_ruling(title)
    assert ruling is not None
    assert a_direction == ruling[2]


def test_判无关时不关联任何假设() -> None:
    """「无关」意味着不进入证据链，因此不能带假设编号。

    这与「中性」的差别是本次裁决的核心：中性是「相关但方向不明、留在证据链里
    等结果」，无关是「这类公告根本不构成证据」。带了假设编号的无关会让下游
    以为它是一条待补充方向的证据。
    """
    ruling = apply_ruling("恒瑞医药关于获得药物临床试验批准通知书的公告")
    assert ruling is not None
    assert ruling[2] == ImpactDirection.IRRELEVANT.value
    assert ruling[1] == ""


def test_判中性与方向时必须关联假设() -> None:
    """反过来，进入证据链的裁定必须说明支持/削弱的是哪一条假设，
    否则方向无从检验（一条证据同时支持又冲突无法验证）。"""
    for title in (
        "恒瑞医药关于药品上市许可申请获受理的提示性公告",
        "恒瑞医药关于获得药品注册证书的公告",
        "恒瑞医药关于撤回药品注册申请的公告",
        "中芯国际关于发行股份购买资产暨关联交易事项的进展公告",
    ):
        ruling = apply_ruling(title)
        assert ruling is not None, title
        assert ruling[1], f"{title} 判为 {ruling[2]} 但未关联假设"
