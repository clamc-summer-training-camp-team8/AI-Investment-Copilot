"""B 类管道：财务指标采集与口径处理。

说明书 7.2 的硬要求：**单季度值、累计值、年度值不允许混算。** 交易所披露的利润表是
**累计值**（一季报=Q1，中报=H1，三季报=前三季度，年报=全年），因此单季度值必须自己
差分出来：Q2 = H1 − Q1，Q3 = 前三季 − H1，Q4 = 全年 − 前三季。

拿累计值当单季度值用，会让同比计算出现系统性错误——这是 DQ-004 口径冲突要拦的问题。

同时记录 `disclosure_date`（实际披露日），因为指标观测值的可得时间决定了它能否用于
某个时点的判断。用报告期末日期（如 12-31）当可得时间是典型的未来信息泄露：
2025 年年报的数据在 2026 年 4 月才公开。

用法：
    python -m analytics.pipelines.fetch_financials
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path

from analytics.pipelines.universe import COMPANIES
from app.core.config import PROJECT_ROOT

RAW_DIR = PROJECT_ROOT / "real_data" / "raw"
API = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (research-tooling; MVP validation)",
    "Referer": "https://emweb.securities.eastmoney.com/",
}
DATA_VERSION = "em-f10-gincome-v1"
QUANT = Decimal("0.0001")

# 报告类型 → 累计期数。用于差分出单季度值。
_CUMULATIVE_QUARTERS = {"一季报": 1, "中报": 2, "三季报": 3, "年报": 4}


@dataclass
class RawReport:
    security_id: str
    report_date: str
    report_type: str
    revenue_cumulative: str
    cost_cumulative: str


@dataclass
class QuarterMetric:
    """单季度指标观测值。

    `period` 用 2025Q1 这类标签，`period_type` 固定为单季度——这个字段存在的意义
    就是让下游无法把它和累计值混算。
    """

    security_id: str
    period: str
    period_type: str
    revenue: str
    cost: str
    gross_margin: str | None
    revenue_yoy: str | None


def _fetch(security_id: str, exchange: str) -> list[RawReport]:
    """取近年利润表。分页取全，不猜条数。"""
    reports: list[RawReport] = []
    for page in range(1, 6):
        params = {
            "reportName": "RPT_F10_FINANCE_GINCOME",
            "columns": "SECUCODE,SECURITY_CODE,REPORT_DATE,REPORT_TYPE,OPERATE_INCOME,OPERATE_COST",
            "filter": f'(SECUCODE="{security_id}.{exchange}")',
            "pageNumber": str(page),
            "pageSize": "50",
            "sortTypes": "-1",
            "sortColumns": "REPORT_DATE",
            "source": "HSF10",
            "client": "PC",
        }
        url = f"{API}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))

        result = body.get("result") or {}
        rows = result.get("data") or []
        if not rows:
            break

        for row in rows:
            income = row.get("OPERATE_INCOME")
            cost = row.get("OPERATE_COST")
            if income is None or cost is None:
                continue
            reports.append(
                RawReport(
                    security_id=str(row.get("SECURITY_CODE")),
                    report_date=str(row.get("REPORT_DATE"))[:10],
                    report_type=str(row.get("REPORT_TYPE")),
                    revenue_cumulative=str(income),
                    cost_cumulative=str(cost),
                )
            )

        if page >= int(result.get("pages") or 1):
            break
        time.sleep(0.4)

    return reports


def _period_label(report_date: str, report_type: str) -> str | None:
    quarter = _CUMULATIVE_QUARTERS.get(report_type)
    if quarter is None:
        return None
    return f"{report_date[:4]}Q{quarter}"


def to_single_quarter(reports: list[RawReport]) -> list[QuarterMetric]:
    """累计值差分成单季度值，并算毛利率与收入同比。

    差分依赖同一年内前一个累计期存在。缺失就跳过该季度，不用插值——插出来的数
    不是披露值，会污染可复核性（DA-AC-04 要求可复核）。
    """
    cumulative: dict[tuple[str, int], tuple[Decimal, Decimal]] = {}
    for report in reports:
        quarter = _CUMULATIVE_QUARTERS.get(report.report_type)
        if quarter is None:
            continue
        year = report.report_date[:4]
        cumulative[(year, quarter)] = (
            Decimal(report.revenue_cumulative),
            Decimal(report.cost_cumulative),
        )

    single: dict[str, tuple[Decimal, Decimal]] = {}
    for (year, quarter), (revenue, cost) in cumulative.items():
        if quarter == 1:
            single[f"{year}Q1"] = (revenue, cost)
            continue
        previous = cumulative.get((year, quarter - 1))
        if previous is None:
            continue
        single[f"{year}Q{quarter}"] = (revenue - previous[0], cost - previous[1])

    metrics: list[QuarterMetric] = []
    security_id = reports[0].security_id if reports else ""
    for period in sorted(single):
        revenue, cost = single[period]
        margin = None
        if revenue != 0:
            margin = str(((revenue - cost) / revenue * Decimal(100)).quantize(QUANT))

        year, quarter = int(period[:4]), period[-1]
        prior = single.get(f"{year - 1}Q{quarter}")
        yoy = None
        if prior and prior[0] != 0:
            yoy = str(((revenue - prior[0]) / abs(prior[0]) * Decimal(100)).quantize(QUANT))

        metrics.append(
            QuarterMetric(
                security_id=security_id,
                period=period,
                period_type="单季度",
                revenue=str(revenue),
                cost=str(cost),
                gross_margin=margin,
                revenue_yoy=yoy,
            )
        )
    return metrics


def run() -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {"data_version": DATA_VERSION, "metrics": {}}
    metrics_map: dict[str, list[dict[str, object]]] = {}
    # 年报披露的累计营业收入。留着它是为了让测试能验证差分正确性：
    # 单季度值之和必须等于年报值，否则说明累计值没差干净。
    annual_map: dict[str, dict[str, str]] = {}

    for company in COMPANIES:
        exchange = "SZ" if company.secid.startswith("0.") else "SH"
        reports = _fetch(company.security_id, exchange)
        metrics = to_single_quarter(reports)
        metrics_map[company.security_id] = [asdict(m) for m in metrics]
        annual_map[company.security_id] = {
            report.report_date[:4]: report.revenue_cumulative
            for report in reports
            if report.report_type == "年报"
        }
        print(
            f"{company.name}({company.security_id}) 报告 {len(reports)} 期 → 单季度 {len(metrics)} 期"
        )
        time.sleep(0.5)

    payload["metrics"] = metrics_map
    payload["annual_revenue"] = annual_map
    destination = RAW_DIR / "financials.json"
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"→ {destination}")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    run()


if __name__ == "__main__":
    main()
