"""关键词基线（说明书 10.2 第 3 步：至少比较关键词法之一）。

基线的作用是回答「AI 是否比最朴素的做法更好」。没有基线，任何准确率数字都无法解读
——85% 听起来不错，但如果关键词法也有 84%，AI 的增量就接近零。

基线刻意做得朴素但不做得愚蠢：一个正经的关键词方案会做的事（词表命中、方向词计数）
都做，但不做语义理解、不做上下文判断。把基线故意做差是自欺欺人。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.enums import ImpactDirection

# 主题词 → 假设。基线只认字面词，不理解业务含义。
TOPIC_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("H1-需求与出货", "出货"),
    ("H1-需求与出货", "销量"),
    ("H1-需求与出货", "产销"),
    ("H1-需求与出货", "订单"),
    ("H1-需求与出货", "中标"),
    ("H1-需求与出货", "收入"),
    ("H2-盈利质量", "毛利"),
    ("H2-盈利质量", "利润"),
    ("H2-盈利质量", "业绩"),
    ("H2-盈利质量", "亏损"),
    ("H2-盈利质量", "盈利"),
    ("H2-盈利质量", "报告"),
    ("H3-产能与扩张", "产能"),
    ("H3-产能与扩张", "投资"),
    ("H3-产能与扩张", "建设"),
    ("H3-产能与扩张", "募集"),
    ("H3-产能与扩张", "扩产"),
    # 跨行业后补的行业主题词。加它们是为了公平：
    # 如果只给 candidate_v2 补医药与半导体词表，却让基线对这两个行业完全失明，
    # 那么 candidate_v2 的优势是构造出来的，不是真本事。基线拿到同一批行业词，
    # 只是仍然停留在「单词命中」这个朴素水平，不做排除项也不做组合判断。
    ("H1-需求与出货", "临床"),
    ("H1-需求与出货", "注册"),
    ("H1-需求与出货", "上市许可"),
    ("H1-需求与出货", "交付"),
    ("H2-盈利质量", "集采"),
    ("H2-盈利质量", "医保"),
    ("H3-产能与扩张", "晶圆"),
    ("H3-产能与扩张", "制程"),
    ("H3-产能与扩张", "收购"),
)

POSITIVE_WORDS = ("增", "涨", "提升", "中标", "签订", "盈利", "扭亏", "新高", "达成")
NEGATIVE_WORDS = ("降", "减", "跌", "亏", "终止", "延期", "处罚", "诉讼", "风险", "下滑")


@dataclass(frozen=True)
class BaselineOutput:
    hypothesis: str
    direction: str


def predict(title: str) -> BaselineOutput:
    """关键词基线预测。命中多个主题时取命中次数最多的。"""
    scores: dict[str, int] = {}
    for hypothesis, keyword in TOPIC_KEYWORDS:
        if keyword in title:
            scores[hypothesis] = scores.get(hypothesis, 0) + 1

    if not scores:
        return BaselineOutput("", ImpactDirection.IRRELEVANT.value)

    hypothesis = max(scores.items(), key=lambda item: (item[1], item[0]))[0]

    positive = sum(1 for word in POSITIVE_WORDS if word in title)
    negative = sum(1 for word in NEGATIVE_WORDS if word in title)
    if negative > positive:
        direction = ImpactDirection.CONFLICT.value
    elif positive > negative:
        direction = ImpactDirection.SUPPORT.value
    else:
        direction = ImpactDirection.NEUTRAL.value

    return BaselineOutput(hypothesis, direction)
