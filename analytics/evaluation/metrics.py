"""效果指标（说明书第 11 节）。

**分母是这个模块的全部重点。** 说明书发布门槛写得很直接：仅有百分比、没有样本数的
结果不得用于验收。因此每个指标都是 `(numerator, denominator)` 一起返回，任何只想拿
到一个浮点数的调用方都拿不到。

命名上的坑，写代码时容易搞错：说明书里的「准确率」分母是 **AI 输出数**，是精确率
（precision）；「召回率」分母是 **人工金标数**。两者都不是 accuracy。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rate:
    """一个带分母的比率。

    分母为 0 时 `value` 是 None，不是 0.0。把「无样本」写成 0% 是最常见的误导。
    """

    name: str
    numerator: int
    denominator: int

    @property
    def value(self) -> float | None:
        if self.denominator == 0:
            return None
        return self.numerator / self.denominator

    def render(self) -> str:
        if self.value is None:
            return f"{self.name}: 无样本（分母 0）"
        return f"{self.name}: {self.value:.1%} ({self.numerator}/{self.denominator})"


@dataclass(frozen=True)
class LinkMetrics:
    """事件关联与方向判断的一组指标。"""

    link_precision: Rate
    link_recall: Rate
    direction_agreement: Rate
    irrelevant_alert_rate: Rate

    def render(self) -> list[str]:
        return [
            self.link_precision.render(),
            self.link_recall.render(),
            self.direction_agreement.render(),
            self.irrelevant_alert_rate.render(),
        ]


def evaluate_links(
    predictions: list[tuple[str, str]],
    truth: list[tuple[str, str]],
) -> LinkMetrics:
    """对齐位置比较预测与金标。两个列表必须同序同长。

    `("", 无关)` 表示判定为不影响任何假设。

    四个指标的口径：
    - 关联准确率 = 关联正确数 / AI 关联数（AI 说有关联的里面对了多少）
    - 关联召回率 = 关联正确数 / 金标关联数（该发现的里面发现了多少）
    - 方向一致率 = 方向一致数 / 已复核数，分母只算**双方都认为有关联**的样本。
      在无关样本上比较方向没有意义，会把大量「都判无关」算成方向一致，虚高。
    - 无关提醒率 = AI 认为有关联但金标认为无关 / AI 关联数。这是研究员感受到的
      噪音，直接决定产品可用性。
    """
    if len(predictions) != len(truth):
        raise ValueError("预测与金标数量不一致，无法逐条对齐")

    predicted_links = 0
    truth_links = 0
    correct_links = 0
    reviewed = 0
    direction_match = 0
    false_alerts = 0

    for (pred_hypothesis, pred_direction), (true_hypothesis, true_direction) in zip(
        predictions, truth, strict=True
    ):
        has_prediction = bool(pred_hypothesis)
        has_truth = bool(true_hypothesis)

        if has_prediction:
            predicted_links += 1
        if has_truth:
            truth_links += 1

        if has_prediction and has_truth:
            if pred_hypothesis == true_hypothesis:
                correct_links += 1
                reviewed += 1
                if pred_direction == true_direction:
                    direction_match += 1
        elif has_prediction and not has_truth:
            false_alerts += 1

    return LinkMetrics(
        link_precision=Rate("事件关联准确率", correct_links, predicted_links),
        link_recall=Rate("事件关联召回率", correct_links, truth_links),
        direction_agreement=Rate("方向一致率", direction_match, reviewed),
        irrelevant_alert_rate=Rate("无关提醒率", false_alerts, predicted_links),
    )


@dataclass(frozen=True)
class EfficiencyMetrics:
    """效率指标（说明书 11：时间节省率；指标字典 MET-005：信息发现提前量）。"""

    task_count: int
    manual_minutes_total: float
    assisted_minutes_total: float
    lead_hours_mean: float | None

    @property
    def time_saving_rate(self) -> float | None:
        """（人工基线时长 − AI辅助时长）/ 人工基线时长。"""
        if self.manual_minutes_total <= 0:
            return None
        return (self.manual_minutes_total - self.assisted_minutes_total) / self.manual_minutes_total

    def render(self) -> list[str]:
        rate = self.time_saving_rate
        lines = [
            f"对照任务数: {self.task_count}",
            f"人工基线合计: {self.manual_minutes_total:.0f} 分钟",
            f"AI 辅助合计: {self.assisted_minutes_total:.0f} 分钟",
        ]
        lines.append(f"时间节省率: {rate:.1%}" if rate is not None else "时间节省率: 无法计算")
        if self.lead_hours_mean is not None:
            lines.append(f"信息发现提前量均值: {self.lead_hours_mean:.2f} 小时")
        else:
            lines.append("信息发现提前量: 缺少人工时间，不计算（MET-005 缺失值规则）")
        return lines
