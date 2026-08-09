"""MVP 研究范围：一个行业、三家公司。

说明书第 4 节要求首期只选一个行业、二至三家公司和一至二类信号，行业与公司由业务
导师确认。这里给出待确认的候选范围（GAP-001 仍未关闭），导师复核的是业务正确性。

选储能与动力电池的理由：三家公司都以公开披露为主要信息源，公告密度足以支撑
200-500 条事件的样本量要求，且同处一条产业链，行业基准可比。

**生存者偏差声明（说明书 10.4）**：这三家都是当前仍上市且经营正常的公司，样本
本身带生存者偏差。本轮不做跨公司横向选股结论，只做「同一公司内事件→假设」的
关联与方向判断评测，这个偏差不影响评测结论，但影响任何收益类推断——报告里必须
写明。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Company:
    """研究对象。

    `org_id` 是巨潮资讯网的机构编号，公告查询必须带它，只用证券代码查不到数据。
    `secid` 是东方财富行情接口的标识，前缀 0=深市、1=沪市。
    """

    security_id: str
    name: str
    org_id: str
    secid: str
    role: str


INDUSTRY = "储能与动力电池"
# 创业板指。基准必须事前确定（说明书 10.3），选它是因为三家公司中两家在创业板，
# 且指数成分与新能源制造业重叠度高。选定后不再更换——事后换基准等于挑结果。
BENCHMARK = Company(
    security_id="399006",
    name="创业板指",
    org_id="",
    secid="0.399006",
    role="基准",
)

COMPANIES: tuple[Company, ...] = (
    Company("300274", "阳光电源", "9900021300", "0.300274", "储能系统与光伏逆变器"),
    Company("300750", "宁德时代", "GD165627", "0.300750", "动力电池与储能电芯"),
    Company("002594", "比亚迪", "gshk0001211", "0.002594", "新能源汽车与电池"),
)

COMPANY_BY_ID = {c.security_id: c for c in COMPANIES}


@dataclass(frozen=True)
class MetricDef:
    """指标口径。复用指标字典的 MET 编号，不另起一套命名。"""

    metric_id: str
    name: str
    unit: str
    period_type: str
    expected_direction: str
    source: str
    note: str = ""


# 沿用指标字典 MET-001~005 的编号与口径，避免出现第三套命名
METRICS: tuple[MetricDef, ...] = (
    MetricDef(
        "MET-001",
        "营业收入同比",
        "%",
        "单季度",
        "越高越好",
        "定期报告",
        "由披露的分季度营业收入计算，不用累计值混算",
    ),
    MetricDef(
        "MET-002",
        "毛利率",
        "%",
        "单季度",
        "不低于阈值",
        "定期报告",
        "由披露的营业收入与营业成本推算，非披露值",
    ),
    MetricDef(
        "MET-004",
        "20日行业中性超额收益",
        "%",
        "事件",
        "随信号方向",
        "行情数据",
        "从首次可得时间的下一交易日起算，窗口结束后生成标签",
    ),
)

# 两类候选信号（说明书 4 节允许 1-2 类）
SIGNAL_TYPES: tuple[str, ...] = ("订单与产能类事件信号", "盈利质量与成本类事件信号")


@dataclass
class UniverseSummary:
    industry: str
    companies: list[str] = field(default_factory=list)
    signal_types: list[str] = field(default_factory=list)

    @classmethod
    def build(cls) -> UniverseSummary:
        return cls(
            industry=INDUSTRY,
            companies=[f"{c.name}({c.security_id})" for c in COMPANIES],
            signal_types=list(SIGNAL_TYPES),
        )
