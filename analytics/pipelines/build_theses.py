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

具体口径：毛利率阈值 = 2022Q1~2024Q3 单季度毛利率的 25 分位向下取整到 0.5。
这段历史全部在最早建立日（2025-01-20）之前已经披露，所以定阈值时用不到任何
未来信息。选 25 分位是朴素规则：低于历史四分之一水平算异常。**阈值按公司单独设**，
不设跨行业统一值——恒瑞毛利率 84%、比亚迪 16%，用同一个阈值没有业务含义。

**样本量与季度数的关系**：说明书目标 1 要求 30-50 条投资逻辑。九家公司下每家
5 个季度 = 45 条，落在区间内。原来三家 × 10 季度 = 30 条贴着下限，直接套用
10 个季度会得到 90 条，超出上限——那不是「样本更多更好」，说明书给上限是因为
每条逻辑都要人工确认，超出人工复核能力的样本量只会让确认流于形式。

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

# 观察期：每家公司 5 个季度，9 家 = 45 条逻辑，落在说明书要求的 30-50 区间。
# 选 2025Q1 起是为了让阈值所依赖的历史（2022Q1~2024Q3）全部早于最早建立日，
# 同时让观察期同时覆盖样本内（切分点 2025-10-01 之前）与样本外。
QUARTERS: tuple[tuple[str, str, str], ...] = (
    ("2025Q1", "2025-01-20", "2025-04-30"),
    ("2025Q2", "2025-04-20", "2025-07-31"),
    ("2025Q3", "2025-07-20", "2025-10-31"),
    ("2025Q4", "2025-10-20", "2026-01-31"),
    ("2026Q1", "2026-01-20", "2026-04-30"),
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
    industry: str
    market: str
    title: str
    core_view: str
    established_on: str
    horizon_end: str
    signal_type: str
    hypotheses: list[HypothesisSpec] = field(default_factory=list)
    invalidation_require_all: bool = True
    invalidation_note: str = ""


@dataclass(frozen=True)
class CompanyThesis:
    """一家公司的假设内容与阈值。

    三条假设骨架跨行业统一（H1 需求与出货 / H2 盈利质量 / H3 产能与扩张），
    骨架统一是为了让评测的分母定义一致；内容与阈值按公司填，因为业务本身不同。

    `margin_threshold` 一律取自 2022Q1~2024Q3 单季度毛利率的 25 分位（见模块文档），
    不是拍的，也不是按结果调的。
    """

    demand: str
    profit: str
    capacity: str
    capacity_rule: str
    revenue_expectation: str
    margin_expectation: str
    margin_threshold: str
    core_view: str


THESES: dict[str, CompanyThesis] = {
    # ——————————— 芯片半导体 ———————————
    "688981": CompanyThesis(
        demand="成熟制程产能利用率与晶圆出货保持增长，国产替代需求是主要驱动",
        profit="毛利率随产能利用率回升，折旧压力不导致盈利持续恶化",
        capacity="资本开支与扩产节奏匹配下游需求，先进制程投入不出现大额减值",
        capacity_rule="出现产能利用率显著下滑或在建工程大额减值则该假设失效（需人工判断）",
        revenue_expectation="15.00",
        margin_expectation="22.00",
        margin_threshold="18.50",
        core_view=(
            "成熟制程代工龙头，国产替代与产能利用率回升支撑收入，"
            "折旧与价格压力是盈利的主要观察点"
        ),
    ),
    "603986": CompanyThesis(
        demand="存储与 MCU 需求随消费电子与工业复苏回升，库存周期见底",
        profit="毛利率随产品结构改善回升，不因存储价格波动持续走低",
        capacity="新品研发与产能储备按计划推进，不出现存货大额跌价",
        capacity_rule="出现存货大额跌价或新品量产延期则该假设失效（需人工判断）",
        revenue_expectation="20.00",
        margin_expectation="38.00",
        margin_threshold="36.00",
        core_view=(
            "存储与 MCU 设计商，需求随下游复苏与库存去化回升，"
            "毛利率对存储价格周期高度敏感，需跟踪产品结构"
        ),
    ),
    "002371": CompanyThesis(
        demand="半导体设备订单随晶圆厂扩产与国产化率提升保持增长",
        profit="规模效应与国产化推进支撑毛利率，不因竞争加剧显著下滑",
        capacity="产能与交付能力跟上订单增长，合同负债转化不出现明显滞后",
        capacity_rule="出现交付延期或合同负债长期不转收入则该假设失效（需人工判断）",
        revenue_expectation="30.00",
        margin_expectation="42.00",
        margin_threshold="41.00",
        core_view=(
            "前道设备国产化核心标的，晶圆厂扩产与国产化率提升支撑订单与收入，"
            "需跟踪毛利率与交付节奏"
        ),
    ),
    # ——————————— 医药 ———————————
    "600276": CompanyThesis(
        demand="创新药放量与授权合作收入接续仿制药集采下滑，研发管线持续推进",
        profit="创新药占比提升支撑高毛利率，集采降价不导致盈利持续恶化",
        capacity="研发投入强度维持，管线推进不出现关键品种研发失败",
        capacity_rule="出现关键在研品种终止或研发投入大幅收缩则该假设失效（需人工判断）",
        revenue_expectation="10.00",
        margin_expectation="85.00",
        margin_threshold="83.50",
        core_view=(
            "创新药转型期，创新药放量与对外授权接续仿制药集采缺口，"
            "毛利率高但集采与研发成败是关键观察点"
        ),
    ),
    "603259": CompanyThesis(
        demand="CXO 订单与在手订单随全球创新药研发投入回暖恢复增长",
        profit="产能利用率与项目结构支撑毛利率，不因价格竞争持续走低",
        capacity="新增产能与地缘政治风险可控，海外基地建设按计划推进",
        capacity_rule="出现海外基地受限或产能闲置则该假设失效（需人工判断）",
        revenue_expectation="12.00",
        margin_expectation="41.00",
        margin_threshold="37.50",
        core_view=(
            "全球医药研发外包龙头，订单随创新药投入周期波动，" "地缘政治与产能利用率是核心风险点"
        ),
    ),
    "000538": CompanyThesis(
        demand="工业药品与健康品渠道保持稳定，不出现持续负增长",
        profit="毛利率随产品结构与原料成本波动，不持续低于历史区间",
        capacity="渠道与品牌投入保持，不出现商誉或投资大额减值",
        capacity_rule="出现大额投资减值或渠道库存积压则该假设失效（需人工判断）",
        revenue_expectation="3.00",
        margin_expectation="27.50",
        margin_threshold="26.00",
        core_view=(
            "中药与健康消费品，增长平稳，毛利率与渠道结构是主要观察点，"
            "历史上曾因证券投资造成业绩波动"
        ),
    ),
    # ——————————— 新能源汽车 ———————————
    "002594": CompanyThesis(
        demand="新能源汽车销量保持增长，出口占比提升对冲国内价格压力",
        profit="规模效应与垂直一体化维持毛利率，价格战不导致盈利持续恶化",
        capacity="海外工厂与产能扩张按计划落地，不出现大额投资减值",
        capacity_rule="出现海外产能计划取消或大额减值则该假设失效（需人工判断）",
        revenue_expectation="12.00",
        margin_expectation="18.50",
        margin_threshold="15.50",
        core_view=(
            "新能源汽车销量与出口结构改善支撑收入，垂直一体化对冲价格战，需跟踪毛利率与海外扩张落地"
        ),
    ),
    "00175": CompanyThesis(
        demand="新能源车型销量放量带动整体销量增长，出口贡献增量",
        profit="平台化与规模效应改善毛利率，新能源转型不持续拖累盈利",
        capacity="品牌与平台整合按计划推进，不出现大额整合损失",
        capacity_rule="出现品牌整合受阻或大额减值则该假设失效（需人工判断）",
        revenue_expectation="25.00",
        margin_expectation="16.50",
        margin_threshold="14.50",
        core_view=(
            "新能源转型见效，销量与出口双增长支撑收入，"
            "平台整合与毛利率改善是核心观察点。港股披露频率低于 A 股"
        ),
    ),
    "09868": CompanyThesis(
        demand="智能车交付量保持增长，新车型周期带动需求回升",
        profit="毛利率随规模与技术服务收入改善，不回落到历史低位",
        capacity="研发与产能投入可持续，现金流不出现明显恶化",
        capacity_rule="出现交付大幅下滑或现金流紧张则该假设失效（需人工判断）",
        revenue_expectation="40.00",
        margin_expectation="13.00",
        margin_threshold="1.50",
        core_view=(
            "新势力整车厂，交付量与车型周期决定收入，毛利率从负值修复中，"
            "盈利质量仍是主要风险。港股仅披露中报与年报，季度颗粒度不足"
        ),
    ),
}


def _hypotheses(thesis_id: str, spec: CompanyThesis) -> list[HypothesisSpec]:
    """三条假设。H1 与 H2 有量化阈值参与自动失效判定，H3 只能人工判断。

    H3 刻意不给 metric_id 与阈值：产能与扩张是否失效要看在建工程、产能利用率、
    减值这些需要读正文才能判断的信息。给它编一个阈值会让「自动失效判定」
    看起来覆盖三条假设，实际上第三条是假的。
    """
    return [
        HypothesisSpec(
            hypothesis_id=f"{thesis_id}-H1-需求与出货",
            content=spec.demand,
            importance="核心",
            metric_id="MET-001",
            expectation_value=spec.revenue_expectation,
            threshold="0.00",
            direction="higher_better",
            required_consecutive=2,
            invalidation_rule="营业收入同比连续 2 个季度转负则该假设失效",
            participates_in_invalidation=True,
        ),
        HypothesisSpec(
            hypothesis_id=f"{thesis_id}-H2-盈利质量",
            content=spec.profit,
            importance="核心",
            metric_id="MET-002",
            expectation_value=spec.margin_expectation,
            threshold=spec.margin_threshold,
            direction="higher_better",
            required_consecutive=2,
            invalidation_rule=(
                f"毛利率连续 2 个季度低于 {spec.margin_threshold}% 则该假设失效"
                "（阈值取 2022Q1~2024Q3 单季度 25 分位）"
            ),
            participates_in_invalidation=True,
        ),
        HypothesisSpec(
            hypothesis_id=f"{thesis_id}-H3-产能与扩张",
            content=spec.capacity,
            importance="重要",
            metric_id="",
            expectation_value="",
            threshold="",
            direction="",
            required_consecutive=1,
            invalidation_rule=spec.capacity_rule,
            participates_in_invalidation=False,
        ),
    ]


def build() -> list[ThesisSpec]:
    theses: list[ThesisSpec] = []
    for company in COMPANIES:
        spec = THESES[company.security_id]
        for quarter, established, horizon in QUARTERS:
            thesis_id = f"THS-{company.security_id}-{quarter}"
            hypotheses = _hypotheses(thesis_id, spec)
            theses.append(
                ThesisSpec(
                    thesis_id=thesis_id,
                    security_id=company.security_id,
                    company=company.name,
                    quarter=quarter,
                    industry=company.industry,
                    market=company.market,
                    title=f"{company.name}{quarter}观察：{company.role}",
                    core_view=spec.core_view,
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
    for industry in sorted({t.industry for t in theses}):
        subset = [t for t in theses if t.industry == industry]
        names = sorted({t.company for t in subset})
        print(f"  {industry}: {len(subset)} 条，{'、'.join(names)}")
    print(
        "说明书目标 1 最低样本 30-50 条投资逻辑：",
        "达到" if 30 <= len(theses) <= 50 else "不在区间",
    )
    print()
    print("全部逻辑落库时状态为草稿，正式化需业务导师确认（说明书 2.2 / 第 4 节）")


if __name__ == "__main__":
    main()
