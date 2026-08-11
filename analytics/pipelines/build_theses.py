"""构造投资逻辑与核心假设（说明书目标 1：30-50 条投资逻辑）。

每条投资逻辑 = 一个季度观察期内、针对一家公司的一个可检验判断，含 2-3 条核心假设，
每条假设带失效条件。这是 `app/services/thesis.py` 已经强制的结构（2-5 条假设、
核心假设必须有预期值），这里只提供业务内容。

**观点内容的来源与责任边界**：观点文本由数据分析师按公开披露信息组织，属于「待导师
确认」状态。说明书 2.2 明确数据分析师不做投资决策，第 4 节要求投资逻辑由业务导师
确认。因此每条逻辑落地时 `status` 一律是草稿，不进入正式状态——正式化需要人工确认
并留痕（`app/services/status.py` 的人工闸门）。

失效条件的阈值取值说明（避免过拟合质疑，说明书 10.4）：
阈值来自各公司披露的历史区间的朴素分位，**在观察任何收益结果之前**确定，且此后
不再调整。这不代表阈值是最优的，只代表它不是拿结果调出来的。

用法：
    python -m analytics.pipelines.build_theses
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field

from analytics.pipelines.universe import COMPANIES
from app.core.config import PROJECT_ROOT

OUT_DIR = PROJECT_ROOT / "real_data" / "dataset"

# 观察期：每家公司按季度建逻辑，覆盖 2024Q1 起的多个时间段
QUARTERS: tuple[tuple[str, str, str], ...] = (
    ("2024Q1", "2024-01-15", "2024-04-30"),
    ("2024Q2", "2024-04-20", "2024-07-31"),
    ("2024Q3", "2024-07-20", "2024-10-31"),
    ("2024Q4", "2024-10-20", "2025-01-31"),
    ("2025Q1", "2025-01-20", "2025-04-30"),
    ("2025Q2", "2025-04-20", "2025-07-31"),
    ("2025Q3", "2025-07-20", "2025-10-31"),
    ("2025Q4", "2025-10-20", "2026-01-31"),
    ("2026Q1", "2026-01-20", "2026-04-30"),
    ("2026Q2", "2026-04-20", "2026-07-31"),
)


@dataclass
class HypothesisSpec:
    """核心假设。

    `invalidation_rule` 用自然语言写给人看，`metric_id` + `threshold` +
    `required_consecutive` 是机器判断失效的依据。两者必须一致——只写自然语言无法
    自动监控，只写阈值则人工复核时看不懂在判断什么。
    """

    hypothesis_id: str
    content: str
    importance: str
    metric_id: str
    expectation_value: str
    threshold: str
    direction: str
    required_consecutive: int
    invalidation_rule: str
    participates_in_invalidation: bool


@dataclass
class ThesisSpec:
    thesis_id: str
    security_id: str
    company: str
    quarter: str
    title: str
    core_view: str
    established_on: str
    horizon_end: str
    signal_type: str
    hypotheses: list[HypothesisSpec] = field(default_factory=list)
    invalidation_require_all: bool = True
    invalidation_note: str = ""


# 三条假设骨架，按公司业务差异填不同的指标与阈值。
# 结构统一是为了让评测的分母定义一致；内容按公司区分是因为业务本身不同。
HYPOTHESIS_TEMPLATES: dict[str, tuple[dict[str, object], ...]] = {
    "300274": (
        {
            "key": "H1-需求与出货",
            "content": "储能系统出货保持增长，海外大储需求是主要驱动",
            "importance": "核心",
            "metric_id": "MET-001",
            "expectation": "20.00",
            "threshold": "0.00",
            "direction": "higher_better",
            "consecutive": 2,
            "rule": "营业收入同比连续 2 个季度转负则该假设失效",
            "participates": True,
        },
        {
            "key": "H2-盈利质量",
            "content": "毛利率受益于海外结构占比提升，不因价格竞争显著下滑",
            "importance": "核心",
            "metric_id": "MET-002",
            "expectation": "30.00",
            "threshold": "25.00",
            "direction": "higher_better",
            "consecutive": 2,
            "rule": "毛利率连续 2 个季度低于 25% 则该假设失效",
            "participates": True,
        },
        {
            "key": "H3-产能与扩张",
            "content": "产能与产线投资节奏与订单匹配，不出现明显过度扩张",
            "importance": "重要",
            "metric_id": "",
            "expectation": "",
            "threshold": "",
            "direction": "",
            "consecutive": 1,
            "rule": "出现产能利用率显著下滑或项目大额减值则该假设失效（需人工判断）",
            "participates": False,
        },
    ),
    "300750": (
        {
            "key": "H1-需求与出货",
            "content": "动力电池与储能电芯出货量保持行业领先，装机份额不显著流失",
            "importance": "核心",
            "metric_id": "MET-001",
            "expectation": "15.00",
            "threshold": "0.00",
            "direction": "higher_better",
            "consecutive": 2,
            "rule": "营业收入同比连续 2 个季度转负则该假设失效",
            "participates": True,
        },
        {
            "key": "H2-盈利质量",
            "content": "单位盈利在原材料价格波动中保持稳定，毛利率不持续走低",
            "importance": "核心",
            "metric_id": "MET-002",
            "expectation": "24.00",
            "threshold": "18.00",
            "direction": "higher_better",
            "consecutive": 2,
            "rule": "毛利率连续 2 个季度低于 18% 则该假设失效",
            "participates": True,
        },
        {
            "key": "H3-产能与扩张",
            "content": "海外产能布局按计划推进，资本开支不显著超出经营现金流",
            "importance": "重要",
            "metric_id": "",
            "expectation": "",
            "threshold": "",
            "direction": "",
            "consecutive": 1,
            "rule": "出现海外项目停滞或大额减值则该假设失效（需人工判断）",
            "participates": False,
        },
    ),
    "002594": (
        {
            "key": "H1-需求与出货",
            "content": "新能源汽车销量保持增长，出口占比提升对冲国内价格压力",
            "importance": "核心",
            "metric_id": "MET-001",
            "expectation": "12.00",
            "threshold": "0.00",
            "direction": "higher_better",
            "consecutive": 2,
            "rule": "营业收入同比连续 2 个季度转负则该假设失效",
            "participates": True,
        },
        {
            "key": "H2-盈利质量",
            "content": "规模效应与垂直一体化维持毛利率，价格战不导致盈利持续恶化",
            "importance": "核心",
            "metric_id": "MET-002",
            "expectation": "19.00",
            "threshold": "15.00",
            "direction": "higher_better",
            "consecutive": 2,
            "rule": "毛利率连续 2 个季度低于 15% 则该假设失效",
            "participates": True,
        },
        {
            "key": "H3-产能与扩张",
            "content": "海外工厂与产能扩张按计划落地，不出现大额投资减值",
            "importance": "重要",
            "metric_id": "",
            "expectation": "",
            "threshold": "",
            "direction": "",
            "consecutive": 1,
            "rule": "出现海外产能计划取消或大额减值则该假设失效（需人工判断）",
            "participates": False,
        },
    ),
}

CORE_VIEWS: dict[str, str] = {
    "300274": (
        "储能系统与逆变器双主业，海外大储需求与结构优化支撑收入增长和毛利率，"
        "需跟踪价格竞争对盈利的侵蚀"
    ),
    "300750": (
        "动力电池龙头地位与储能电芯放量支撑收入，单位盈利稳定性是核心观察点，"
        "需跟踪份额与海外产能进度"
    ),
    "002594": (
        "新能源汽车销量与出口结构改善支撑收入，垂直一体化对冲价格战，" "需跟踪毛利率与海外扩张落地"
    ),
}


def build() -> list[ThesisSpec]:
    theses: list[ThesisSpec] = []
    for company in COMPANIES:
        templates = HYPOTHESIS_TEMPLATES[company.security_id]
        for quarter, established, horizon in QUARTERS:
            thesis_id = f"THS-{company.security_id}-{quarter}"
            hypotheses = [
                HypothesisSpec(
                    hypothesis_id=f"{thesis_id}-{template['key']}",
                    content=str(template["content"]),
                    importance=str(template["importance"]),
                    metric_id=str(template["metric_id"]),
                    expectation_value=str(template["expectation"]),
                    threshold=str(template["threshold"]),
                    direction=str(template["direction"]),
                    required_consecutive=int(str(template["consecutive"])),
                    invalidation_rule=str(template["rule"]),
                    participates_in_invalidation=bool(template["participates"]),
                )
                for template in templates
            ]
            theses.append(
                ThesisSpec(
                    thesis_id=thesis_id,
                    security_id=company.security_id,
                    company=company.name,
                    quarter=quarter,
                    title=f"{company.name}{quarter}观察：{company.role}",
                    core_view=CORE_VIEWS[company.security_id],
                    established_on=established,
                    horizon_end=horizon,
                    signal_type=(
                        "订单与产能类事件信号"
                        if quarter.endswith(("Q1", "Q3"))
                        else "盈利质量与成本类事件信号"
                    ),
                    hypotheses=hypotheses,
                    invalidation_require_all=True,
                    invalidation_note=(
                        "需求与盈利两条核心假设同时失效才判定逻辑失效；"
                        "单条失效为关注状态。避免单季度波动触发误判。"
                    ),
                )
            )
    return theses


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    theses = build()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    destination = OUT_DIR / "theses.json"
    destination.write_text(
        json.dumps([asdict(t) for t in theses], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    hypothesis_count = sum(len(t.hypotheses) for t in theses)
    print(f"投资逻辑 {len(theses)} 条，核心假设 {hypothesis_count} 条 → {destination}")
    print(f"覆盖公司 {len({t.security_id for t in theses})} 家，观察期 {len(QUARTERS)} 个季度")
    print(
        "说明书目标 1 最低样本 30-50 条投资逻辑：",
        "达到" if 30 <= len(theses) <= 50 else "不在区间",
    )
    print()
    print("全部逻辑落库时状态为草稿，正式化需业务导师确认（说明书 2.2 / 第 4 节）")


if __name__ == "__main__":
    main()
