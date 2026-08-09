"""候选抽取规则 v2：面向公告标题的事件抽取。

**为什么需要 v2**：`app/ai/providers/local.py` 的词表是按研报正文的措辞写的
（装机、需求、订单、毛利率），而公告标题的措辞完全不同（产销快报、业绩预告、
年度报告）。v1 在 1382 条真实标题上只触发 19 次且全错。这是真实能力缺口，
不是实现缺陷。

**开发纪律**（说明书 10.2 第 2、4 步）：

- 词表**只看样本内数据**（2025-10-01 之前）构造，样本外数据在定稿前没有看过。
- 定稿后不再依据样本外结果调整。样本外那一次就是最终成绩。

这样得到的样本外数字才是对「规则能否泛化到未见过的时间段」的诚实回答。若拿全样本
调词表再报全样本准确率，数字会好看，但没有任何预测意义。

v2 仍然是确定性规则，不外发数据，与 local 提供者的合规约束一致。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.enums import ImpactDirection

# 标题主题 → 假设。按公告标题的实际措辞写，顺序敏感。
# 先判排除项：说明会、利润分配、会计政策这些含财务词但不含经营信息的标题，
# 是 v1 误报的主要来源。
_EXCLUSIONS = re.compile(
    r"说明会|网上互动|路演|接待.{0,4}调研|利润分配|资本公积|转增股本|分红|派息"
    r"|会计政策|会计估计|审计机构|续聘|章程|议事规则|独立董事|监事|董事会决议"
    r"|股东大会|换届|制度|多元化政策|内部控制|募集资金.{0,6}存放|三会"
)

_TOPIC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "H1-需求与出货",
        re.compile(
            r"产销快报|产销数据|经营数据|销量|出货|交付|中标|签订|订单|重大合同|框架协议|战略合作|采购"
        ),
    ),
    (
        "H2-盈利质量",
        re.compile(
            r"业绩预告|业绩快报|年度报告|半年度报告|季度报告|年报|中报|减值|计提|毛利|营业收入"
        ),
    ),
    (
        "H3-产能与扩张",
        re.compile(
            r"对外投资|投资设立|扩产|产能|建设项目|新建|增资|募集资金|定向增发|可转债|发行.{0,6}股份|存托凭证|H股"
        ),
    ),
)

# 方向词。公告标题的方向表达比正文更程式化，可以列得比较全。
_POSITIVE = re.compile(
    r"预增|增长|增加|上升|提升|提高|扭亏|盈利|新高|中标|签订|达成|投产|获得|通过|完成"
)
_NEGATIVE = re.compile(
    r"预减|预亏|亏损|下降|下滑|减少|终止|解除|延期|减值|计提|处罚|诉讼|仲裁|问询|立案|风险提示|异动"
)


@dataclass(frozen=True)
class CandidateOutput:
    hypothesis: str
    direction: str
    confidence: float


def predict(title: str) -> CandidateOutput:
    """按标题抽取假设关联与影响方向。

    定期报告与产销快报的标题本身**不含方向**（「2024年1月产销快报」看不出增减），
    判中性并交人工。这是产品设计要的行为：方向不明的证据进人工队列，不由机器拍。
    """
    if _EXCLUSIONS.search(title):
        return CandidateOutput("", ImpactDirection.IRRELEVANT.value, 0.8)

    hypothesis = ""
    for name, pattern in _TOPIC_PATTERNS:
        if pattern.search(title):
            hypothesis = name
            break

    if not hypothesis:
        return CandidateOutput("", ImpactDirection.IRRELEVANT.value, 0.6)

    positive = bool(_POSITIVE.search(title))
    negative = bool(_NEGATIVE.search(title))

    if positive and negative:
        return CandidateOutput(hypothesis, ImpactDirection.NEUTRAL.value, 0.4)
    if negative:
        return CandidateOutput(hypothesis, ImpactDirection.CONFLICT.value, 0.7)
    if positive:
        return CandidateOutput(hypothesis, ImpactDirection.SUPPORT.value, 0.7)
    return CandidateOutput(hypothesis, ImpactDirection.NEUTRAL.value, 0.5)
