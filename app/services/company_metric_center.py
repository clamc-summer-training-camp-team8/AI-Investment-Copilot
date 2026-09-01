"""企业指标中心：真实量化数据采集、入库与查询。"""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from statistics import pstdev
from typing import Any

import httpx

from app.core.domain import ObservationRecord, UnitOfWork


@dataclass(frozen=True)
class CenterMetric:
    metric_id: str
    name: str
    category: str
    unit: str
    frequency: str
    definition: str
    period_type: str = "日值"
    source_id: str = "eastmoney-quant-api"


@dataclass(frozen=True)
class RawObservation:
    metric_id: str
    period: str
    observed_on: date
    value: Decimal
    unit: str
    period_type: str


METRICS: tuple[CenterMetric, ...] = (
    CenterMetric(
        "MKT-OPEN-D", "开盘价", "价格与成交量", "交易币种", "交易日", "当日开盘成交价格。"
    ),
    CenterMetric(
        "MKT-HIGH-D", "最高价", "价格与成交量", "交易币种", "交易日", "当日最高成交价格。"
    ),
    CenterMetric("MKT-LOW-D", "最低价", "价格与成交量", "交易币种", "交易日", "当日最低成交价格。"),
    CenterMetric(
        "MKT-CLOSE-D",
        "前复权收盘价",
        "价格与成交量",
        "交易币种",
        "交易日",
        "交易日收盘后的前复权价格。",
    ),
    CenterMetric(
        "MKT-CHANGE-D",
        "涨跌额",
        "价格与成交量",
        "交易币种",
        "交易日",
        "收盘价相对上一交易日的变动金额。",
    ),
    CenterMetric(
        "MKT-AMPLITUDE-D",
        "振幅",
        "价格与成交量",
        "%",
        "交易日",
        "当日最高价与最低价相对前收盘价的波动幅度。",
    ),
    CenterMetric("MKT-VOLUME-D", "成交量", "价格与成交量", "手", "交易日", "当日成交量。"),
    CenterMetric(
        "MKT-AMOUNT-D",
        "成交额",
        "价格与成交量",
        "交易币种",
        "交易日",
        "当日成交金额，按证券交易市场本币计价。",
    ),
    CenterMetric(
        "MKT-TURNOVER-D", "换手率", "价格与成交量", "%", "交易日", "当日成交量占可流通股份的比例。"
    ),
    CenterMetric(
        "MKT-CHANGE-PCT-D",
        "涨跌幅",
        "价格与成交量",
        "%",
        "交易日",
        "收盘价相对上一交易日的变化率。",
    ),
    CenterMetric(
        "TECH-MA5-D",
        "5日移动平均",
        "技术指标",
        "交易币种",
        "交易日",
        "最近5个交易日收盘价算术平均值。",
    ),
    CenterMetric(
        "TECH-MA20-D",
        "20日移动平均",
        "技术指标",
        "交易币种",
        "交易日",
        "最近20个交易日收盘价算术平均值。",
    ),
    CenterMetric(
        "TECH-MA60-D",
        "60日移动平均",
        "技术指标",
        "交易币种",
        "交易日",
        "最近60个交易日收盘价算术平均值。",
    ),
    CenterMetric(
        "TECH-AVG-VOLUME20-D",
        "20日平均成交量",
        "技术指标",
        "手",
        "交易日",
        "最近20个交易日成交量的算术平均值。",
    ),
    CenterMetric(
        "TECH-VOLUME-RATIO-D",
        "成交量相对20日均值",
        "技术指标",
        "倍",
        "交易日",
        "当日成交量相对20日平均成交量的倍数。",
    ),
    CenterMetric(
        "TECH-MOMENTUM20-D",
        "20日价格变动",
        "技术指标",
        "%",
        "交易日",
        "收盘价相对20个交易日前收盘价的变化率。",
    ),
    CenterMetric(
        "TECH-RSI14-D",
        "RSI（14日）",
        "技术指标",
        "",
        "交易日",
        "基于最近14期上涨与下跌幅度计算的相对强弱指标。",
    ),
    CenterMetric(
        "TECH-VOL20-D",
        "20日年化波动率",
        "技术指标",
        "%",
        "交易日",
        "最近20个交易日日收益率标准差按252日年化。",
    ),
    CenterMetric(
        "VAL-PE-TTM-D",
        "市盈率（TTM）",
        "估值指标",
        "倍",
        "交易日",
        "总市值除以最近十二个月归母净利润。",
    ),
    CenterMetric(
        "VAL-PB-MRQ-D",
        "市净率（MRQ）",
        "估值指标",
        "倍",
        "交易日",
        "总市值除以最近一期归母净资产。",
    ),
    CenterMetric(
        "VAL-PS-TTM-D",
        "市销率（TTM）",
        "估值指标",
        "倍",
        "交易日",
        "总市值除以最近十二个月营业收入。",
    ),
    CenterMetric(
        "VAL-MARKET-CAP-D",
        "总市值",
        "估值指标",
        "交易币种",
        "交易日",
        "证券全部已发行股份对应的市场价值，按证券交易市场本币计价。",
    ),
    CenterMetric(
        "FIN-REVENUE-CUM",
        "营业总收入",
        "财务与运营",
        "报告币种",
        "随财报",
        "报告期累计营业总收入。",
        "累计",
    ),
    CenterMetric(
        "FIN-REVENUE-YOY",
        "营业收入同比",
        "财务与运营",
        "%",
        "随财报",
        "报告期累计营业收入相对上年同期的变化率。",
        "累计",
    ),
    CenterMetric(
        "FIN-NET-PROFIT-CUM",
        "归母净利润",
        "财务与运营",
        "报告币种",
        "随财报",
        "报告期累计归属于母公司股东的净利润。",
        "累计",
    ),
    CenterMetric(
        "FIN-NET-PROFIT-YOY",
        "归母净利润同比",
        "财务与运营",
        "%",
        "随财报",
        "报告期累计归母净利润相对上年同期的变化率。",
        "累计",
    ),
    CenterMetric(
        "FIN-DEDUCTED-NP-CUM",
        "扣非归母净利润",
        "财务与运营",
        "报告币种",
        "随财报",
        "报告期累计扣除非经常性损益后的归母净利润。",
        "累计",
    ),
    CenterMetric(
        "FIN-EPS",
        "基本每股收益",
        "财务与运营",
        "报告币种/股",
        "随财报",
        "报告期基本每股收益。",
        "累计",
    ),
    CenterMetric(
        "FIN-BPS",
        "每股净资产",
        "财务与运营",
        "报告币种/股",
        "随财报",
        "报告期末归属于普通股股东的每股净资产。",
        "期末",
    ),
    CenterMetric(
        "FIN-GROSS-MARGIN",
        "销售毛利率",
        "财务与运营",
        "%",
        "随财报",
        "营业收入扣除营业成本后的利润率。",
        "累计",
    ),
    CenterMetric(
        "FIN-ROE",
        "净资产收益率",
        "财务与运营",
        "%",
        "随财报",
        "归母净利润相对加权平均净资产的收益率。",
        "累计",
    ),
    CenterMetric(
        "FIN-ROIC",
        "投入资本回报率",
        "财务与运营",
        "%",
        "随财报",
        "企业税后经营利润相对投入资本的回报率。",
        "累计",
    ),
    CenterMetric(
        "FIN-DEBT-RATIO",
        "资产负债率",
        "财务与运营",
        "%",
        "随财报",
        "负债总额占资产总额的比例。",
        "期末",
    ),
    CenterMetric(
        "FIN-OPERATING-CASHFLOW",
        "经营活动现金流净额",
        "财务与运营",
        "报告币种",
        "随财报",
        "报告期经营活动产生的现金流量净额。",
        "累计",
    ),
    CenterMetric(
        "FIN-TOTAL-ASSETS",
        "资产总额",
        "财务与运营",
        "报告币种",
        "随财报",
        "报告期末资产总额。",
        "期末",
    ),
    CenterMetric(
        "FIN-TOTAL-EQUITY",
        "所有者权益合计",
        "财务与运营",
        "报告币种",
        "随财报",
        "报告期末所有者权益合计。",
        "期末",
    ),
    CenterMetric(
        "FIN-OCF-PER-SHARE",
        "每股经营现金流",
        "财务与运营",
        "报告币种/股",
        "随财报",
        "经营活动现金流净额折算到每股。",
        "累计",
    ),
    CenterMetric(
        "FIN-CURRENT-RATIO",
        "流动比率",
        "财务与运营",
        "倍",
        "随财报",
        "流动资产相对流动负债的覆盖倍数。",
        "期末",
    ),
    CenterMetric(
        "FIN-QUICK-RATIO",
        "速动比率",
        "财务与运营",
        "倍",
        "随财报",
        "速动资产相对流动负债的覆盖倍数。",
        "期末",
    ),
    CenterMetric(
        "FIN-CASH-RATIO",
        "现金比率",
        "财务与运营",
        "倍",
        "随财报",
        "现金及现金等价物相对流动负债的覆盖倍数。",
        "期末",
    ),
    CenterMetric(
        "FIN-INVENTORY-TURNOVER",
        "存货周转率",
        "财务与运营",
        "次",
        "随财报",
        "报告期存货周转效率。",
        "累计",
    ),
    CenterMetric(
        "FIN-OPERATING-CYCLE",
        "营业周期",
        "财务与运营",
        "天",
        "随财报",
        "存货周转天数与应收账款周转天数之和。",
        "累计",
    ),
    CenterMetric(
        "FIN-INTEREST-COVERAGE",
        "利息保障倍数",
        "财务与运营",
        "倍",
        "随财报",
        "经营业绩对利息费用的覆盖倍数。",
        "累计",
    ),
    CenterMetric(
        "FIN-TAX-RATE",
        "实际税率",
        "财务与运营",
        "%",
        "随财报",
        "报告期所得税费用相对利润总额的比例。",
        "累计",
    ),
    CenterMetric(
        "FIN-RD-EXPENSE-CUM",
        "研发费用",
        "财务与运营",
        "报告币种",
        "随财报",
        "报告期累计研发费用。",
        "累计",
        "sina-finance-api",
    ),
    CenterMetric(
        "FIN-RD-RATIO",
        "研发费用率",
        "财务与运营",
        "%",
        "随财报",
        "报告期累计研发费用占营业收入的比例。",
        "累计",
        "sina-finance-api",
    ),
    CenterMetric(
        "FIN-INVENTORY-END",
        "期末存货",
        "财务与运营",
        "报告币种",
        "随财报",
        "报告期末存货账面余额。",
        "期末",
        "sina-finance-api",
    ),
    CenterMetric(
        "FIN-RECEIVABLE-END",
        "期末应收账款",
        "财务与运营",
        "报告币种",
        "随财报",
        "报告期末应收账款账面余额。",
        "期末",
        "sina-finance-api",
    ),
    CenterMetric(
        "FIN-CASH-END",
        "期末货币资金",
        "财务与运营",
        "报告币种",
        "随财报",
        "报告期末货币资金及现金等价物余额。",
        "期末",
        "sina-finance-api",
    ),
    CenterMetric(
        "FIN-TOTAL-LIABILITIES",
        "负债合计",
        "财务与运营",
        "报告币种",
        "随财报",
        "报告期末负债合计。",
        "期末",
        "sina-finance-api",
    ),
    CenterMetric(
        "INDUSTRY-CLOSE-D",
        "所属行业指数",
        "宏观及行业",
        "点",
        "交易日",
        "公司所属东方财富行业板块的收盘点位。",
    ),
    CenterMetric(
        "INDUSTRY-CHANGE-PCT-D",
        "所属行业指数涨跌幅",
        "宏观及行业",
        "%",
        "交易日",
        "所属行业板块指数相对上一交易日的变化率。",
    ),
    CenterMetric(
        "MACRO-CPI-YOY-M",
        "居民消费价格同比",
        "宏观及行业",
        "%",
        "月度",
        "全国居民消费价格指数相对上年同月的变化率。",
        "月值",
    ),
    CenterMetric(
        "MACRO-PPI-YOY-M",
        "工业生产者出厂价格同比",
        "宏观及行业",
        "%",
        "月度",
        "全国工业生产者出厂价格指数相对上年同月的变化率。",
        "月值",
    ),
    CenterMetric(
        "MACRO-PMI-M",
        "制造业采购经理指数",
        "宏观及行业",
        "点",
        "月度",
        "反映制造业景气水平的采购经理指数。",
        "月值",
    ),
)

METRIC_BY_ID = {item.metric_id: item for item in METRICS}

# 这些指标的数值口径随交易市场变化，不能把“交易币种”直接展示给研究员。
_CURRENCY_METRIC_IDS = {
    "MKT-OPEN-D",
    "MKT-HIGH-D",
    "MKT-LOW-D",
    "MKT-CLOSE-D",
    "MKT-CHANGE-D",
    "MKT-AMOUNT-D",
    "TECH-MA5-D",
    "TECH-MA20-D",
    "TECH-MA60-D",
    "VAL-MARKET-CAP-D",
}


def _decimal_or_none(value: Any) -> Decimal | None:
    """把东方财富返回的数值安全转换为 Decimal；空值和占位符不入库。"""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text or text in {"-", "--", "—", "null", "None", "nan", "NaN"}:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _decimal(value: str | Decimal | float | int) -> Decimal:
    """兼容旧调用方的严格转换；外部行情字段使用宽松转换。"""
    parsed = _decimal_or_none(value)
    if parsed is None:
        raise ValueError(f"无效数值: {value}")
    return parsed


def _currency_for_security(security_id: str, ticker: str | None) -> str:
    """按证券行情市场返回展示用 ISO 货币代码。"""
    suffix = ticker.rsplit(".", 1)[-1].upper() if ticker and "." in ticker else ""
    if suffix == "HK":
        return "HKD"
    if suffix in {"US", "NASDAQ", "NYSE"}:
        return "USD"
    # 市场主数据中的港股代码可能没有保留交易所后缀。
    if not suffix and len(security_id) == 5 and security_id.isdigit():
        return "HKD"
    return "CNY"


def _display_unit(definition: CenterMetric, actual_unit: str, currency: str) -> str:
    if definition.metric_id in _CURRENCY_METRIC_IDS:
        return currency
    return actual_unit or definition.unit


def _display_value(metric_id: str, value: Decimal | None) -> str | None:
    """指标中心的头部数值按用户可读精度返回，原始观测仍保留完整精度。"""
    if value is None:
        return None
    if metric_id in {"MKT-CLOSE-D", "MKT-CHANGE-PCT-D"}:
        return format(value.quantize(Decimal("0.01")), "f")
    return str(value)


def _catalog_category(metric_id: str, category: str | None) -> str:
    """把历史指标目录归一到指标中心的固定导航分类。"""
    if category in {"价格与成交量", "技术指标", "财务与运营", "估值指标", "宏观及行业"}:
        return category
    if metric_id.startswith("MKT-"):
        return "价格与成交量"
    if metric_id.startswith("TECH-"):
        return "技术指标"
    if metric_id.startswith("VAL-"):
        return "估值指标"
    if metric_id.startswith(("MACRO-", "INDUSTRY-")):
        return "宏观及行业"
    return "财务与运营"


def _metric_definitions(uow: UnitOfWork) -> tuple[CenterMetric, ...]:
    """合并数据库指标字典与自动采集目录；数据库定义优先。"""
    definitions = {item.metric_id: item for item in METRICS}
    for record in uow.metrics.search(limit=1000):
        definitions[record.metric_id] = CenterMetric(
            metric_id=record.metric_id,
            name=record.name,
            category=_catalog_category(record.metric_id, record.category),
            unit=record.unit,
            frequency=record.frequency or "按来源更新",
            definition=record.definition or "指标口径暂未补充。",
            period_type=record.period_type,
            source_id=record.source_id or "metric-catalog",
        )
    return tuple(definitions.values())


def refresh_security_metrics(uow: UnitOfWork, security_id: str) -> dict[str, Any]:
    security = uow.securities.get(security_id)
    if security is None:
        raise ValueError("证券不存在")
    ticker = security.ticker or security.security_id
    sources = (
        ("行情与技术", _fetch_market),
        ("估值", _fetch_valuation),
        ("行业", _fetch_industry),
        ("财务运营", _fetch_financials),
        ("财务备用源", _fetch_financials_sina),
        ("宏观统计", _fetch_macro),
    )

    def fetch_source(fetcher):
        timeout = httpx.Timeout(3.0, connect=2.0)
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as client:
            return fetcher(client, security.security_id, ticker)

    observations: list[RawObservation] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=len(sources)) as executor:
        futures = [(name, executor.submit(fetch_source, fetcher)) for name, fetcher in sources]
        for name, future in futures:
            try:
                observations.extend(future.result())
            except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
                errors.append(f"{name}数据源暂不可用（{type(exc).__name__}）")
    # 行情源短暂不可用时，仍可从已入库的真实 OHLCV 观测补齐派生指标。
    # 这里只做确定性计算，不生成任何外部数据或缺失值。
    if not any(row.metric_id == "MKT-CLOSE-D" for row in observations):
        observations.extend(_derive_market_metrics(uow, security.security_id, ticker))
    inserted = _store(uow, security.security_id, observations)
    return {
        "security_id": security.security_id,
        "fetched": len(observations),
        "inserted": inserted,
        "errors": errors,
    }


def metric_center(uow: UnitOfWork, security_id: str, *, periods: int = 60) -> list[dict[str, Any]]:
    security = uow.securities.get(security_id)
    ticker = security.ticker if security else None
    currency = _currency_for_security(security_id, ticker)
    result: list[dict[str, Any]] = []
    observations_by_metric: dict[str, list[ObservationRecord]] = {}
    for row in uow.observations.list_for_security(security_id):
        if row.actual_value is not None:
            observations_by_metric.setdefault(row.metric_id, []).append(row)
    for definition in _metric_definitions(uow):
        rows = observations_by_metric.get(definition.metric_id, [])
        rows = sorted(rows, key=lambda row: row.observation_date)[-periods:]
        if not rows:
            continue
        latest = rows[-1]
        latest_value = latest.actual_value
        if latest_value is None:
            continue
        previous = rows[-2] if len(rows) > 1 else None
        previous_value = previous.actual_value if previous else None
        unit = _display_unit(definition, latest.unit, currency)
        result.append(
            {
                "metric_id": definition.metric_id,
                "name": definition.name,
                "category": definition.category,
                "unit": unit,
                "frequency": definition.frequency,
                "definition": definition.definition,
                "source_id": definition.source_id,
                "latest_value": _display_value(definition.metric_id, latest_value),
                "latest_period": latest.period,
                "latest_date": latest.observation_date.isoformat(),
                "previous_value": _display_value(definition.metric_id, previous_value),
                "change_value": _display_value(definition.metric_id, latest_value - previous_value)
                if previous_value is not None
                else None,
                "change_rate": str((latest_value - previous_value) / abs(previous_value) * 100)
                if previous_value
                else None,
                "observations": [
                    {
                        "period": row.period,
                        "date": row.observation_date.isoformat(),
                        "value": str(row.actual_value),
                    }
                    for row in rows
                ],
            }
        )
    return result


def _fetch_market(client: httpx.Client, security_id: str, ticker: str) -> list[RawObservation]:
    try:
        rows = _klines(client, _secid(security_id, ticker), limit=180)
    except (httpx.HTTPError, ValueError):
        rows = _sina_klines(client, security_id, ticker, limit=180)
    output: list[RawObservation] = []
    closes: list[Decimal] = []
    volumes: list[Decimal] = []
    returns: list[float] = []
    currency = _currency_for_security(security_id, ticker)
    for row in rows:
        day, open_, close, high, low, volume, amount, _amplitude, change_pct, _change, turnover = (
            row
        )
        change = row[9]
        amplitude = row[7]
        try:
            observed = date.fromisoformat(day)
        except ValueError:
            continue
        values = {
            "MKT-OPEN-D": (_decimal_or_none(open_), currency),
            "MKT-HIGH-D": (_decimal_or_none(high), currency),
            "MKT-LOW-D": (_decimal_or_none(low), currency),
            "MKT-CLOSE-D": (_decimal_or_none(close), currency),
            "MKT-CHANGE-D": (_decimal_or_none(change), currency),
            "MKT-AMPLITUDE-D": (_decimal_or_none(amplitude), "%"),
            "MKT-VOLUME-D": (_decimal_or_none(volume), "手"),
            "MKT-AMOUNT-D": (_decimal_or_none(amount), currency),
            "MKT-TURNOVER-D": (_decimal_or_none(turnover), "%"),
            "MKT-CHANGE-PCT-D": (_decimal_or_none(change_pct), "%"),
        }
        for metric_id, (value, unit) in values.items():
            if value is not None:
                output.append(RawObservation(metric_id, day, observed, value, unit, "日值"))
        close_value = values["MKT-CLOSE-D"][0]
        if close_value is None:
            continue
        closes.append(close_value)
        volume_value = values["MKT-VOLUME-D"][0]
        if volume_value is not None:
            volumes.append(volume_value)
        if len(closes) > 1 and closes[-2] != 0:
            returns.append(float(closes[-1] / closes[-2] - 1))
        for window, metric_id in ((5, "TECH-MA5-D"), (20, "TECH-MA20-D"), (60, "TECH-MA60-D")):
            if len(closes) >= window:
                output.append(
                    RawObservation(
                        metric_id,
                        day,
                        observed,
                        sum(closes[-window:], Decimal(0)) / Decimal(window),
                        currency,
                        "滚动",
                    )
                )
        if len(volumes) >= 20:
            average_volume = sum(volumes[-20:], Decimal(0)) / Decimal(20)
            output.append(
                RawObservation("TECH-AVG-VOLUME20-D", day, observed, average_volume, "手", "滚动")
            )
            if average_volume:
                output.append(
                    RawObservation(
                        "TECH-VOLUME-RATIO-D",
                        day,
                        observed,
                        volumes[-1] / average_volume,
                        "倍",
                        "滚动",
                    )
                )
        if len(closes) >= 21 and closes[-21] != 0:
            output.append(
                RawObservation(
                    "TECH-MOMENTUM20-D",
                    day,
                    observed,
                    (closes[-1] / closes[-21] - 1) * 100,
                    "%",
                    "滚动",
                )
            )
        if len(returns) >= 20:
            volatility = Decimal(str(pstdev(returns[-20:]) * math.sqrt(252) * 100))
            output.append(RawObservation("TECH-VOL20-D", day, observed, volatility, "%", "滚动"))
        if len(closes) >= 15:
            changes = [closes[i] - closes[i - 1] for i in range(len(closes) - 14, len(closes))]
            gains = sum((max(change, Decimal(0)) for change in changes), Decimal(0)) / Decimal(14)
            losses = sum((max(-change, Decimal(0)) for change in changes), Decimal(0)) / Decimal(14)
            rsi = (
                Decimal(100)
                if losses == 0
                else Decimal(100) - Decimal(100) / (Decimal(1) + gains / losses)
            )
            output.append(RawObservation("TECH-RSI14-D", day, observed, rsi, "", "滚动"))
    return output


def _derive_market_metrics(uow: UnitOfWork, security_id: str, ticker: str) -> list[RawObservation]:
    """用已有真实行情观测补齐派生指标，作为行情刷新失败时的降级路径。"""
    close_rows = sorted(
        (
            row
            for row in uow.observations.list_for_metric(security_id, "MKT-CLOSE-D")
            if row.actual_value is not None
        ),
        key=lambda row: row.observation_date,
    )
    if not close_rows:
        return []
    high_by_period = {
        row.period: row for row in uow.observations.list_for_metric(security_id, "MKT-HIGH-D")
    }
    low_by_period = {
        row.period: row for row in uow.observations.list_for_metric(security_id, "MKT-LOW-D")
    }
    volume_rows = {
        row.period: row for row in uow.observations.list_for_metric(security_id, "MKT-VOLUME-D")
    }
    currency = _currency_for_security(security_id, ticker)
    output: list[RawObservation] = []
    closes: list[Decimal] = []
    volumes: list[Decimal] = []
    for index, close_row in enumerate(close_rows):
        close = close_row.actual_value
        if close is None:
            continue
        period = close_row.period
        day = close_row.observation_date
        closes.append(close)
        volume_row = volume_rows.get(period)
        if volume_row and volume_row.actual_value is not None:
            volumes.append(volume_row.actual_value)
        if index > 0 and closes[-2] != 0:
            output.append(
                RawObservation("MKT-CHANGE-D", period, day, close - closes[-2], currency, "日值")
            )
            high = high_by_period.get(period)
            low = low_by_period.get(period)
            if high and low and high.actual_value is not None and low.actual_value is not None:
                output.append(
                    RawObservation(
                        "MKT-AMPLITUDE-D",
                        period,
                        day,
                        (high.actual_value - low.actual_value) / closes[-2] * 100,
                        "%",
                        "日值",
                    )
                )
        for window, metric_id in ((5, "TECH-MA5-D"), (20, "TECH-MA20-D"), (60, "TECH-MA60-D")):
            if len(closes) >= window:
                output.append(
                    RawObservation(
                        metric_id,
                        period,
                        day,
                        sum(closes[-window:], Decimal(0)) / Decimal(window),
                        currency,
                        "滚动",
                    )
                )
        if len(volumes) >= 20:
            average_volume = sum(volumes[-20:], Decimal(0)) / Decimal(20)
            output.append(
                RawObservation("TECH-AVG-VOLUME20-D", period, day, average_volume, "手", "滚动")
            )
            if average_volume:
                output.append(
                    RawObservation(
                        "TECH-VOLUME-RATIO-D",
                        period,
                        day,
                        volumes[-1] / average_volume,
                        "倍",
                        "滚动",
                    )
                )
        if len(closes) >= 21 and closes[-21] != 0:
            output.append(
                RawObservation(
                    "TECH-MOMENTUM20-D", period, day, (close / closes[-21] - 1) * 100, "%", "滚动"
                )
            )
    return output


def _fetch_valuation(client: httpx.Client, security_id: str, ticker: str) -> list[RawObservation]:
    query = _data_center(
        client,
        "RPT_VALUEANALYSIS_DET",
        f'(SECURITY_CODE="{security_id}")',
        "TRADE_DATE",
        60,
        web=True,
    )
    output: list[RawObservation] = []
    currency = _currency_for_security(security_id, ticker)
    for row in reversed(query):
        day = str(row["TRADE_DATE"])[:10]
        try:
            observed = date.fromisoformat(day)
        except ValueError:
            continue
        for metric_id, field, unit in (
            ("VAL-PE-TTM-D", "PE_TTM", "倍"),
            ("VAL-PB-MRQ-D", "PB_MRQ", "倍"),
            ("VAL-PS-TTM-D", "PS_TTM", "倍"),
            ("VAL-MARKET-CAP-D", "TOTAL_MARKET_CAP", currency),
        ):
            value = _decimal_or_none(row.get(field))
            if value is not None:
                output.append(RawObservation(metric_id, day, observed, value, unit, "日值"))
    return output


def _fetch_industry(client: httpx.Client, security_id: str, ticker: str) -> list[RawObservation]:
    del ticker
    query = _data_center(
        client,
        "RPT_VALUEANALYSIS_DET",
        f'(SECURITY_CODE="{security_id}")',
        "TRADE_DATE",
        1,
        web=True,
    )
    board_code = str(query[0].get("BOARD_CODE") or "") if query else ""
    if not board_code:
        return []
    output: list[RawObservation] = []
    rows = _klines(client, f"90.{board_code}", limit=60)
    if not rows:
        raise ValueError("行业板块行情为空")
    for row in rows:
        (
            day,
            _open,
            close,
            _high,
            _low,
            _volume,
            _amount,
            _amplitude,
            change_pct,
            _change,
            _turnover,
        ) = row
        try:
            observed = date.fromisoformat(day)
        except ValueError:
            continue
        close_value = _decimal_or_none(close)
        change_value = _decimal_or_none(change_pct)
        if close_value is not None:
            output.append(
                RawObservation("INDUSTRY-CLOSE-D", day, observed, close_value, "点", "日值")
            )
        if change_value is not None:
            output.append(
                RawObservation("INDUSTRY-CHANGE-PCT-D", day, observed, change_value, "%", "日值")
            )
    return output


def _fetch_financials(client: httpx.Client, security_id: str, ticker: str) -> list[RawObservation]:
    secu_code = ticker
    if "." not in secu_code:
        suffix = "SH" if security_id.startswith(("5", "6", "9")) else "SZ"
        secu_code = f"{security_id}.{suffix}"
    rows = _data_center(
        client, "RPT_F10_FINANCE_MAINFINADATA", f'(SECUCODE="{secu_code}")', "REPORT_DATE", 16
    )
    output: list[RawObservation] = []
    for row in reversed(rows):
        day = str(row.get("NOTICE_DATE") or row["REPORT_DATE"])[:10]
        period = str(row.get("REPORT_DATE_NAME") or row["REPORT_DATE"])[:16]
        try:
            observed = date.fromisoformat(day)
        except ValueError:
            continue
        currency = str(row.get("CURRENCY") or "报告币种")
        for metric_id, field, unit, period_type in (
            ("FIN-REVENUE-CUM", "TOTALOPERATEREVE", currency, "累计"),
            ("FIN-REVENUE-YOY", "TOTALOPERATEREVETZ", "%", "累计"),
            ("FIN-NET-PROFIT-CUM", "PARENTNETPROFIT", currency, "累计"),
            ("FIN-NET-PROFIT-YOY", "PARENTNETPROFITTZ", "%", "累计"),
            ("FIN-DEDUCTED-NP-CUM", "KCFJCXSYJLR", currency, "累计"),
            ("FIN-EPS", "EPSJB", f"{currency}/股", "累计"),
            ("FIN-BPS", "BPS", f"{currency}/股", "期末"),
            ("FIN-GROSS-MARGIN", "XSMLL", "%", "累计"),
            ("FIN-ROE", "ROEJQ", "%", "累计"),
            ("FIN-ROIC", "ROIC", "%", "累计"),
            ("FIN-DEBT-RATIO", "ZCFZL", "%", "期末"),
            ("FIN-OPERATING-CASHFLOW", "NETCASH_OPERATE_PK", currency, "累计"),
            ("FIN-TOTAL-ASSETS", "TOTAL_ASSETS_PK", currency, "期末"),
            ("FIN-TOTAL-EQUITY", "TOTAL_EQUITY_PK", currency, "期末"),
            ("FIN-OCF-PER-SHARE", "MGJYXJJE", f"{currency}/股", "累计"),
            ("FIN-CURRENT-RATIO", "LD", "倍", "期末"),
            ("FIN-QUICK-RATIO", "SD", "倍", "期末"),
            ("FIN-CASH-RATIO", "CASH_RATIO", "倍", "期末"),
            ("FIN-INVENTORY-TURNOVER", "CHZZL", "次", "累计"),
            ("FIN-OPERATING-CYCLE", "OPERATE_CYCLE", "天", "累计"),
            ("FIN-INTEREST-COVERAGE", "INTEREST_COVERAGE_RATIO", "倍", "累计"),
            ("FIN-TAX-RATE", "TAXRATE", "%", "累计"),
        ):
            value = _decimal_or_none(row.get(field))
            if value is not None:
                output.append(RawObservation(metric_id, period, observed, value, unit, period_type))
    return output


def _fetch_financials_sina(
    client: httpx.Client, security_id: str, ticker: str
) -> list[RawObservation]:
    """从新浪财经公开财报接口补齐三表和财务指标。

    该接口是 AKShare 所使用的 HTTP 接口，但这里直接用 httpx 调用，避免把
    pandas/AKShare 引入后端运行时。没有报告或非 A 股证券时返回空列表。
    """
    paper_code = _sina_paper_code(security_id, ticker)
    if paper_code is None:
        return []
    output: list[RawObservation] = []
    for source in ("fzb", "lrb", "llb", "gjzb"):
        payload = _sina_finance_payload(client, paper_code, source)
        reports = _sina_reports(payload)
        for period, report in reports:
            period_date = _parse_date(period)
            if period_date is None:
                continue
            observed_on = _parse_date(report.get("publish_date")) or period_date
            unit = _sina_currency(report.get("rCurrency"))
            values: dict[str, Decimal] = {}
            for item in report.get("data") or []:
                title = _normalize_financial_label(item.get("item_title"))
                value = _decimal_or_none(item.get("item_value"))
                metric_id = _sina_metric_id(title)
                if value is None or metric_id is None:
                    continue
                values.setdefault(metric_id, value)
            for metric_id, value in values.items():
                definition = METRIC_BY_ID.get(metric_id)
                if definition is None:
                    continue
                metric_unit = (
                    unit
                    if definition.unit == "报告币种"
                    else definition.unit.replace("报告币种", unit)
                )
                output.append(
                    RawObservation(
                        metric_id, period, observed_on, value, metric_unit, definition.period_type
                    )
                )
            revenue = values.get("FIN-REVENUE-CUM")
            rd_expense = values.get("FIN-RD-EXPENSE-CUM")
            if revenue and rd_expense is not None and revenue != 0:
                output.append(
                    RawObservation(
                        "FIN-RD-RATIO", period, observed_on, rd_expense / revenue * 100, "%", "累计"
                    )
                )
    return output


def _sina_paper_code(security_id: str, ticker: str) -> str | None:
    code = security_id.strip().upper()
    if "." in ticker:
        code = ticker.split(".", 1)[0].strip().upper()
    if len(code) != 6 or not code.isdigit():
        return None
    market = "sh" if code.startswith(("5", "6", "9")) else "sz"
    return f"{market}{code}"


def _sina_finance_payload(client: httpx.Client, paper_code: str, source: str) -> dict[str, Any]:
    response = client.get(
        "https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022",
        params={"paperCode": paper_code, "source": source, "type": "0", "page": "1", "num": "1000"},
    )
    response.raise_for_status()
    payload = response.json() or {}
    return payload if isinstance(payload, dict) else {}


def _sina_reports(payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    data = payload.get("result", {}).get("data", {})
    report_list = data.get("report_list") or {}
    dates = data.get("report_date") or []
    ordered_periods = [str(item.get("date_value")) for item in dates if item.get("date_value")]
    if not ordered_periods:
        ordered_periods = [str(key) for key in report_list]
    reports: list[tuple[str, dict[str, Any]]] = []
    for period in ordered_periods:
        report = report_list.get(period)
        if isinstance(report, dict):
            reports.append((period, report))
    return reports


def _normalize_financial_label(value: Any) -> str:
    return "".join(str(value or "").split()).replace("（", "(").replace("）", ")")


def _sina_currency(value: Any) -> str:
    text = str(value or "").strip()
    if text in {"人民币", "人民币元", "CNY", "RMB"}:
        return "CNY"
    if text in {"港币", "港元", "HKD"}:
        return "HKD"
    if text in {"美元", "USD"}:
        return "USD"
    return "报告币种"


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit() and len(text) == 8:
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    if "T" in text:
        text = text.split("T", 1)[0]
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _sina_metric_id(label: str) -> str | None:
    if "营业收入" in label and any(
        keyword in label for keyword in ("同比", "增长", "增幅", "增长率")
    ):
        return "FIN-REVENUE-YOY"
    if "净利润" in label and any(
        keyword in label for keyword in ("同比", "增长", "增幅", "增长率")
    ):
        return "FIN-NET-PROFIT-YOY"
    # “营业收入同比/增长率”等派生字段不能误当成收入金额。
    if any(keyword in label for keyword in ("营业总收入", "营业收入")) and not any(
        keyword in label for keyword in ("同比", "增长", "增幅", "增长率")
    ):
        return "FIN-REVENUE-CUM"
    mappings = (
        (
            (
                "归属于母公司股东的净利润",
                "归属母公司股东的净利润",
                "归属于上市公司股东的净利润",
                "归母净利润",
            ),
            "FIN-NET-PROFIT-CUM",
        ),
        (("扣除非经常性损益后的净利润", "扣非归母净利润", "扣非净利润"), "FIN-DEDUCTED-NP-CUM"),
        (("基本每股收益",), "FIN-EPS"),
        (("每股净资产",), "FIN-BPS"),
        (("销售毛利率", "毛利率"), "FIN-GROSS-MARGIN"),
        (("净资产收益率", "加权净资产收益率"), "FIN-ROE"),
        (("投入资本回报率",), "FIN-ROIC"),
        (("资产负债率",), "FIN-DEBT-RATIO"),
        (("经营活动产生的现金流量净额", "经营活动现金流量净额"), "FIN-OPERATING-CASHFLOW"),
        (("资产总计", "资产总额"), "FIN-TOTAL-ASSETS"),
        (("所有者权益合计", "股东权益合计"), "FIN-TOTAL-EQUITY"),
        (("每股经营现金流",), "FIN-OCF-PER-SHARE"),
        (("流动比率",), "FIN-CURRENT-RATIO"),
        (("速动比率",), "FIN-QUICK-RATIO"),
        (("现金比率",), "FIN-CASH-RATIO"),
        (("存货周转率",), "FIN-INVENTORY-TURNOVER"),
        (("营业周期",), "FIN-OPERATING-CYCLE"),
        (("利息保障倍数",), "FIN-INTEREST-COVERAGE"),
        (("实际税率",), "FIN-TAX-RATE"),
        (("研发费用",), "FIN-RD-EXPENSE-CUM"),
        (("存货",), "FIN-INVENTORY-END"),
        (("应收账款",), "FIN-RECEIVABLE-END"),
        (("货币资金", "现金及现金等价物"), "FIN-CASH-END"),
        (("负债合计",), "FIN-TOTAL-LIABILITIES"),
    )
    for keywords, metric_id in mappings:
        if any(keyword in label for keyword in keywords):
            return metric_id
    return None


def _fetch_macro(client: httpx.Client, security_id: str, ticker: str) -> list[RawObservation]:
    del security_id, ticker
    output: list[RawObservation] = []
    for report, metric_id, field in (
        ("RPT_ECONOMY_CPI", "MACRO-CPI-YOY-M", "NATIONAL_SAME"),
        ("RPT_ECONOMY_PPI", "MACRO-PPI-YOY-M", "BASE_SAME"),
        ("RPT_ECONOMY_PMI", "MACRO-PMI-M", "MAKE_INDEX"),
    ):
        rows = _data_center(client, report, "", "REPORT_DATE", 24, web=True)
        for row in reversed(rows):
            if row.get(field) is None:
                continue
            try:
                observed = date.fromisoformat(str(row["REPORT_DATE"])[:10])
            except ValueError:
                continue
            value = _decimal_or_none(row.get(field))
            if value is None:
                continue
            output.append(
                RawObservation(
                    metric_id,
                    observed.strftime("%Y-%m"),
                    observed,
                    value,
                    "%" if metric_id != "MACRO-PMI-M" else "点",
                    "月值",
                )
            )
    return output


def _data_center(
    client: httpx.Client, report: str, filter_: str, sort: str, size: int, *, web: bool = False
) -> list[dict[str, Any]]:
    base = (
        "https://datacenter-web.eastmoney.com/api/data/v1/get"
        if web
        else "https://datacenter.eastmoney.com/securities/api/data/v1/get"
    )
    response = client.get(
        base,
        params={
            "reportName": report,
            "columns": "ALL",
            "filter": filter_,
            "pageNumber": "1",
            "pageSize": str(size),
            "sortTypes": "-1",
            "sortColumns": sort,
        },
    )
    response.raise_for_status()
    return list(((response.json() or {}).get("result") or {}).get("data") or [])


def _klines(client: httpx.Client, secid: str, *, limit: int) -> list[list[str]]:
    params = {
        "secid": secid,
        "klt": "101",
        "fqt": "1",
        "lmt": str(limit),
        "end": "20500101",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
    }
    headers = {"Referer": "https://quote.eastmoney.com/"}
    last_error: Exception | None = None
    for endpoint in ("https://push2his.eastmoney.com/api/qt/stock/kline/get",):
        try:
            response = client.get(endpoint, params=params, headers=headers)
            response.raise_for_status()
            values = ((response.json() or {}).get("data") or {}).get("klines") or []
            return [str(item).split(",") for item in values if len(str(item).split(",")) >= 11]
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return []


def _sina_klines(
    client: httpx.Client, security_id: str, ticker: str, *, limit: int
) -> list[list[str]]:
    """新浪公开日线作为东方财富行情不可用时的真实数据降级源。"""
    symbol = _sina_paper_code(security_id, ticker)
    if symbol is None:
        raise ValueError("新浪行情暂不支持该证券市场")
    response = client.get(
        "https://quotes.sina.cn/cn/api/openapi.php/CN_MarketDataService.getKLineData",
        params={"symbol": symbol, "scale": "240", "ma": "no", "datalen": str(limit)},
    )
    response.raise_for_status()
    rows = ((response.json() or {}).get("result") or {}).get("data") or []
    output: list[list[str]] = []
    previous_close: Decimal | None = None
    for row in rows:
        close = _decimal_or_none(row.get("close"))
        high = _decimal_or_none(row.get("high"))
        low = _decimal_or_none(row.get("low"))
        volume = _decimal_or_none(row.get("volume"))
        change = close - previous_close if close is not None and previous_close else None
        change_pct = (
            change / previous_close * 100 if change is not None and previous_close else None
        )
        amplitude = (
            (high - low) / previous_close * 100
            if high is not None and low is not None and previous_close
            else None
        )
        output.append(
            [
                str(row.get("day") or ""),
                str(row.get("open") or "--"),
                str(row.get("close") or "--"),
                str(row.get("high") or "--"),
                str(row.get("low") or "--"),
                str(volume / 100 if volume is not None else "--"),
                "--",
                str(amplitude if amplitude is not None else "--"),
                str(change_pct if change_pct is not None else "--"),
                str(change if change is not None else "--"),
                "--",
            ]
        )
        if close is not None:
            previous_close = close
    return output


def _secid(security_id: str, ticker: str) -> str:
    suffix = ticker.split(".", 1)[1].upper() if "." in ticker else ""
    market = {"SZ": "0", "SH": "1", "HK": "116"}.get(suffix)
    if market is None:
        # 港股主数据有时只保存五位代码，没有交易所后缀。
        market = (
            "116"
            if len(security_id) == 5 and security_id.isdigit()
            else "1"
            if security_id.startswith(("5", "6", "9"))
            else "0"
        )
    return f"{market}.{security_id}"


def _store(uow: UnitOfWork, security_id: str, rows: list[RawObservation]) -> int:
    records: list[ObservationRecord] = []
    data_version = "eastmoney-company-center-v1"
    seen = uow.observations.existing_keys(security_id, data_version)
    for row in rows:
        key = (row.metric_id, row.period)
        if key in seen:
            continue
        seen.add(key)
        records.append(
            ObservationRecord(
                security_id=security_id,
                metric_id=row.metric_id,
                period=row.period,
                observation_date=row.observed_on,
                unit=row.unit,
                actual_value=row.value,
                period_type=row.period_type,
                data_version=data_version,
            )
        )
    return uow.observations.add_many_if_absent(records)
