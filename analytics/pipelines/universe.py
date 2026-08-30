"""MVP 研究范围：三个行业，每行业三家公司。

说明书第 4 节建议首期只选一个行业、二至三家公司。本轮按业务要求扩到三个行业
各三家（半导体、医药、新能源汽车），行业与公司由业务导师指定，导师复核业务正确性。

**跨行业扩展带来的新约束，必须写在这里而不是藏在代码里**：

1. 基准不能再用单一指数。原来三家公司同处储能产业链，共用创业板指还算可比；
   现在跨三个行业，用同一个基准算超额收益等于把行业轮动当成个股 alpha。
   所以基准改成按行业配，且**事前确定、选定后不换**（说明书 10.3）。

2. 毛利率不能跨行业横向比。医药 CXO、晶圆制造、整车制造的成本结构完全不同，
   毛利率阈值只在同行业内有意义。失效阈值按公司单独设，不设跨行业统一阈值。

3. 吉利与小鹏在香港上市，不在 A 股。三个数据源的接口、会计准则、披露频率都不同：
   - 公告：巨潮 column 从 szse 改 hke，orgId 取自 hke_stock.json
   - 财务：东财 F10 报表名从 RPT_F10_FINANCE_GINCOME 改 RPT_HKF10_FN_INCOME，
     返回的是香港会计准则长表（一行一科目），不是 A 股的宽表
   - 披露频率：港股不强制季报。小鹏只有中报与年报，**没有三季报**，
     所以它的单季度指标期数天然少于 A 股公司，这不是数据缺失，是制度差异
   混市场比较必须显式声明这些差异，不能当作同质样本。

**生存者偏差声明（说明书 10.4）**：九家都是当前仍上市且经营正常的公司，样本带
生存者偏差。本轮不做跨公司横向选股结论，只做「同一公司内事件→假设」的关联与
方向判断评测，这个偏差不影响评测结论，但影响任何收益类推断。
"""

from __future__ import annotations

from dataclasses import dataclass, field

SEMICONDUCTOR = "芯片半导体"
PHARMA = "医药"
AUTO = "新能源汽车"

INDUSTRIES: tuple[str, ...] = (SEMICONDUCTOR, PHARMA, AUTO)

MARKET_A = "A股"
MARKET_HK = "港股"


@dataclass(frozen=True)
class Company:
    """研究对象。

    `org_id` 是巨潮资讯网的机构编号，公告查询必须带它，只用证券代码查不到数据。
    A 股取自 szse_stock.json，港股取自 hke_stock.json，两套编号不通用。

    `secid` 是东方财富行情接口的标识：0=深市、1=沪市、116=港股。

    `market` 决定走哪一套采集接口与会计准则，见模块文档第 3 条。
    """

    security_id: str
    name: str
    org_id: str
    secid: str
    industry: str
    role: str
    market: str = MARKET_A

    @property
    def is_hk(self) -> bool:
        return self.market == MARKET_HK

    @property
    def tencent_symbol(self) -> str:
        """腾讯行情标识：sh/sz/hk + 代码。

        行情主源用腾讯而不是东财，因为东财的 kline 接口在本环境会直接拒连
        （RemoteDisconnected），换 host、换 UA、加退避都无效。腾讯同一接口
        覆盖 A 股、港股与三个基准指数，且支持前复权。
        """
        if self.is_hk:
            return f"hk{self.security_id}"
        return f"{'sz' if self.secid.startswith('0.') else 'sh'}{self.security_id}"

    @property
    def secucode(self) -> str:
        """东财 F10 的证券标识。港股是 00175.HK，A 股是 688981.SH。"""
        if self.is_hk:
            return f"{self.security_id}.HK"
        return f"{self.security_id}.{'SZ' if self.secid.startswith('0.') else 'SH'}"


COMPANIES: tuple[Company, ...] = (
    # 半导体：覆盖晶圆制造、存储设计、前道设备三个环节
    Company("688981", "中芯国际", "gshk0000981", "1.688981", SEMICONDUCTOR, "晶圆代工"),
    Company("603986", "兆易创新", "9900026561", "1.603986", SEMICONDUCTOR, "存储与MCU设计"),
    Company("002371", "北方华创", "9900006137", "0.002371", SEMICONDUCTOR, "半导体设备"),
    # 医药：覆盖创新药、CXO 外包、中药消费三条不同的商业模式
    Company("600276", "恒瑞医药", "gssh0600276", "1.600276", PHARMA, "创新药"),
    Company("603259", "药明康德", "9900035584", "1.603259", PHARMA, "医药研发外包"),
    Company("000538", "云南白药", "gssz0000538", "0.000538", PHARMA, "中药与健康消费"),
    # 新能源汽车：两家港股，注意披露制度差异
    Company("002594", "比亚迪", "gshk0001211", "0.002594", AUTO, "整车与动力电池"),
    Company("00175", "吉利汽车", "gshk0000175", "116.00175", AUTO, "整车", market=MARKET_HK),
    Company("09868", "小鹏汽车", "9900052637", "116.09868", AUTO, "新势力整车", market=MARKET_HK),
)

COMPANY_BY_ID = {c.security_id: c for c in COMPANIES}


def company_for_financials(security_id: str) -> Company:
    """返回财务采集所需的最小证券上下文；已登记样本优先，其他 A/H 股按代码推断市场。"""
    known = COMPANY_BY_ID.get(security_id)
    if known is not None:
        return known
    if len(security_id) == 6 and security_id[0] in {"0", "3"}:
        return Company(security_id, security_id, "", f"0.{security_id}", "未分类", "通用财务")
    if len(security_id) == 6 and security_id[0] == "6":
        return Company(security_id, security_id, "", f"1.{security_id}", "未分类", "通用财务")
    if len(security_id) == 5 and security_id.isdigit():
        return Company(security_id, security_id, "", f"116.{security_id}", "未分类", "通用财务", market=MARKET_HK)
    raise ValueError(f"暂不支持自动识别该证券市场：{security_id}")


def companies_of(industry: str) -> tuple[Company, ...]:
    return tuple(c for c in COMPANIES if c.industry == industry)


# 基准按行业事前确定（说明书 10.3）。选定后不换——事后换基准等于挑结果。
# 半导体用科创50：中芯国际在科创板，另两家与科创板半导体成分高度重叠。
# 医药用中证医药：三家分处创新药/CXO/中药，医药总指数比任何细分指数更中性。
# 新能源汽车用中证新能源汽车：两家港股个股与该指数成分重叠，且它是人民币计价，
#   避免拿恒指去比 A 股比亚迪造成的市场错配。
BENCHMARKS: dict[str, Company] = {
    SEMICONDUCTOR: Company("000688", "科创50", "", "1.000688", SEMICONDUCTOR, "基准"),
    PHARMA: Company("000913", "中证医药", "", "1.000913", PHARMA, "基准"),
    AUTO: Company("399976", "中证新能源汽车", "", "0.399976", AUTO, "基准"),
}
# 两家港股用人民币计价的中证新能源汽车指数做基准，而不是恒生指数。
# 理由：吉利与小鹏的经营主体与收入都在境内，行业景气度由国内新能源车市场决定；
# 恒指是宽基且受港股整体流动性影响，用它做基准会把港股折价当成个股 alpha。
# 代价是存在市场错配（个股港币计价、指数人民币计价），汇率波动会进到超额收益里，
# 这条限制必须写进报告，不能假装不存在。


def benchmark_for(security_id: str) -> Company:
    """取某只证券所属行业的基准。跨行业混用同一基准会把行业轮动算成个股 alpha。"""
    company = COMPANY_BY_ID.get(security_id)
    if company is None:
        raise KeyError(f"不在研究范围内的证券: {security_id}")
    return BENCHMARKS[company.industry]


def all_quote_targets() -> tuple[Company, ...]:
    """需要抓行情的全部标的：九家公司 + 三个行业基准。"""
    return (*COMPANIES, *BENCHMARKS.values())


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
        "由披露的分季度营业收入计算，不用累计值混算。港股按香港会计准则的营运收入。",
    ),
    MetricDef(
        "MET-002",
        "毛利率",
        "%",
        "单季度",
        "不低于阈值",
        "定期报告",
        "由营业收入与营业成本推算，非披露值。阈值按公司设，不跨行业比较。",
    ),
    MetricDef(
        "MET-004",
        "20日行业中性超额收益",
        "%",
        "事件",
        "随信号方向",
        "行情数据",
        "从首次可得时间的下一交易日起算，窗口结束后生成标签。基准按行业取。",
    ),
)

METRIC_BY_ID = {m.metric_id: m for m in METRICS}

# 两类候选信号（说明书 4 节允许 1-2 类）
SIGNAL_TYPES: tuple[str, ...] = ("订单与产能类事件信号", "盈利质量与成本类事件信号")


@dataclass
class UniverseSummary:
    industries: list[str] = field(default_factory=list)
    companies: list[str] = field(default_factory=list)
    benchmarks: list[str] = field(default_factory=list)
    signal_types: list[str] = field(default_factory=list)

    @classmethod
    def build(cls) -> UniverseSummary:
        return cls(
            industries=list(INDUSTRIES),
            companies=[f"{c.industry}/{c.name}({c.security_id},{c.market})" for c in COMPANIES],
            benchmarks=[f"{k}→{v.name}({v.security_id})" for k, v in BENCHMARKS.items()],
            signal_types=list(SIGNAL_TYPES),
        )
