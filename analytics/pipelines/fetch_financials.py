"""B 类管道：财务指标采集与口径处理。

说明书 7.2 的硬要求：**单季度值、累计值、年度值不允许混算。** 交易所披露的利润表是
**累计值**（一季报=Q1，中报=H1，三季报=前三季度，年报=全年），因此单季度值必须自己
差分出来：Q2 = H1 − Q1，Q3 = 前三季 − H1，Q4 = 全年 − 前三季。

拿累计值当单季度值用，会让同比计算出现系统性错误——这是 DQ-004 口径冲突要拦的问题。

同时记录 `disclosure_date`（实际披露日），因为指标观测值的可得时间决定了它能否用于
某个时点的判断。用报告期末日期（如 12-31）当可得时间是典型的未来信息泄露：
2025 年年报的数据在 2026 年 4 月才公开。

**港股与 A 股的两处口径差异**（跨市场比较必须显式处理，不能当同质样本）：

- 接口与准则不同：A 股用 RPT_F10_FINANCE_GINCOME 的宽表（OPERATE_INCOME/OPERATE_COST），
  港股用 RPT_HKF10_FN_INCOME 的长表（一行一科目，取「营运收入」与「销售成本」），
  科目按香港会计准则。两者都是累计值，因此差分逻辑通用。
- 披露频率不同：港股不强制季报。小鹏只有中报与年报，没有三季报，所以它只能差分出
  Q1 与 Q2，Q3/Q4 无法单独还原。这是制度差异不是数据缺失，缺就跳过，绝不插值。

用法：
    python -m analytics.pipelines.fetch_financials
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path

from analytics.pipelines.http import request_json
from analytics.pipelines.universe import COMPANIES, Company
from app.core.config import PROJECT_ROOT

RAW_DIR = PROJECT_ROOT / "real_data" / "raw"
API = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (research-tooling; MVP validation)",
    "Referer": "https://emweb.securities.eastmoney.com/",
}
DATA_VERSION = "em-f10-gincome-v2"
QUANT = Decimal("0.0001")

# 港股长表里对应营业收入与营业成本的科目名（香港会计准则）
HK_REVENUE_ITEM = "营运收入"
HK_COST_ITEM = "销售成本"

# 报告类型 → 累计期数。用于差分出单季度值。
_CUMULATIVE_QUARTERS = {"一季报": 1, "中报": 2, "三季报": 3, "年报": 4}


@dataclass
class RawReport:
    security_id: str
    report_date: str
    report_type: str
    revenue_cumulative: str
    cost_cumulative: str
    notice_date: str | None = None
    """实际披露日（A 股来自接口 NOTICE_DATE）。

    港股长表没有这个字段，只能留空并在下游退回保守估计。
    """


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
    disclosure_date: str | None = None
    """该单季度值实际可得的日期。

    差分出来的季度以「较晚那期的披露日」为准：Q2 = H1 − Q1，要等 H1 发布才算得出来，
    所以可得日是 H1 的披露日，不是 Q1 的。
    """


def _pages(params: dict[str, str], *, page_size: int = 500) -> list[dict[str, object]]:
    """按页取全。不猜条数，读接口返回的总页数。"""
    rows: list[dict[str, object]] = []
    for page in range(1, 8):
        query = {**params, "pageNumber": str(page), "pageSize": str(page_size)}
        body = request_json(f"{API}?{urllib.parse.urlencode(query)}", headers=HEADERS)
        result = body.get("result") or {}
        batch = result.get("data") or []
        if not batch:
            break
        rows.extend(batch)
        if page >= int(result.get("pages") or 1):
            break
        time.sleep(0.4)
    return rows


def _fetch_a_share(company: Company) -> list[RawReport]:
    """A 股利润表：宽表，一行一期。"""
    rows = _pages(
        {
            "reportName": "RPT_F10_FINANCE_GINCOME",
            "columns": (
                "SECUCODE,SECURITY_CODE,REPORT_DATE,REPORT_TYPE,"
                "NOTICE_DATE,OPERATE_INCOME,OPERATE_COST"
            ),
            "filter": f'(SECUCODE="{company.secucode}")',
            "sortTypes": "-1",
            "sortColumns": "REPORT_DATE",
            "source": "HSF10",
            "client": "PC",
        },
        page_size=50,
    )

    reports: list[RawReport] = []
    for row in rows:
        income = row.get("OPERATE_INCOME")
        cost = row.get("OPERATE_COST")
        if income is None or cost is None:
            continue
        notice = row.get("NOTICE_DATE")
        reports.append(
            RawReport(
                security_id=company.security_id,
                report_date=str(row.get("REPORT_DATE"))[:10],
                report_type=str(row.get("REPORT_TYPE")),
                revenue_cumulative=str(income),
                cost_cumulative=str(cost),
                notice_date=str(notice)[:10] if notice else None,
            )
        )
    return reports


def _fetch_hk(company: Company) -> list[RawReport]:
    """港股利润表：长表，一行一科目，需要按报告期把科目拼回一行。

    只有营运收入与销售成本都齐的报告期才入样本——缺一个就算不出毛利率，
    半条记录比没有记录更危险。
    """
    rows = _pages(
        {
            "reportName": "RPT_HKF10_FN_INCOME",
            "columns": "ALL",
            "filter": f'(SECUCODE="{company.secucode}")',
            "sortTypes": "-1",
            "sortColumns": "REPORT_DATE",
            "source": "F10",
            "client": "PC",
        }
    )

    grouped: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        item = str(row.get("ITEM_NAME") or "")
        if item not in (HK_REVENUE_ITEM, HK_COST_ITEM):
            continue
        amount = row.get("AMOUNT")
        if amount is None:
            continue
        key = (str(row.get("REPORT_DATE"))[:10], str(row.get("REPORT_TYPE")))
        grouped.setdefault(key, {})[item] = str(amount)

    reports: list[RawReport] = []
    for (report_date, report_type), items in grouped.items():
        if HK_REVENUE_ITEM not in items or HK_COST_ITEM not in items:
            continue
        reports.append(
            RawReport(
                security_id=company.security_id,
                report_date=report_date,
                report_type=report_type,
                revenue_cumulative=items[HK_REVENUE_ITEM],
                cost_cumulative=items[HK_COST_ITEM],
            )
        )
    return reports


def fetch_company(company: Company) -> list[RawReport]:
    return _fetch_hk(company) if company.is_hk else _fetch_a_share(company)


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
    notices: dict[tuple[str, int], str | None] = {}
    for report in reports:
        quarter = _CUMULATIVE_QUARTERS.get(report.report_type)
        if quarter is None:
            continue
        year = report.report_date[:4]
        cumulative[(year, quarter)] = (
            Decimal(report.revenue_cumulative),
            Decimal(report.cost_cumulative),
        )
        notices[(year, quarter)] = report.notice_date

    single: dict[str, tuple[Decimal, Decimal]] = {}
    disclosed: dict[str, str | None] = {}
    for (year, quarter), (revenue, cost) in cumulative.items():
        if quarter == 1:
            single[f"{year}Q1"] = (revenue, cost)
            disclosed[f"{year}Q1"] = notices.get((year, 1))
            continue
        previous = cumulative.get((year, quarter - 1))
        if previous is None:
            continue
        period = f"{year}Q{quarter}"
        single[period] = (revenue - previous[0], cost - previous[1])
        # 差分值要等较晚那期发布才算得出来，可得日取当期披露日。
        disclosed[period] = notices.get((year, quarter))

    metrics: list[QuarterMetric] = []
    security_id = reports[0].security_id if reports else ""
    for period in sorted(single):
        revenue, cost = single[period]
        margin = None
        if revenue != 0:
            margin = str(((revenue - cost) / revenue * Decimal(100)).quantize(QUANT))

        metric_year = int(period[:4])
        metric_quarter = period[-1]
        prior = single.get(f"{metric_year - 1}Q{metric_quarter}")
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
                disclosure_date=disclosed.get(period),
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
        reports = fetch_company(company)
        metrics = to_single_quarter(reports)
        metrics_map[company.security_id] = [asdict(m) for m in metrics]
        annual_map[company.security_id] = {
            report.report_date[:4]: report.revenue_cumulative
            for report in reports
            if report.report_type == "年报"
        }
        print(
            f"{company.industry}/{company.name}({company.security_id},{company.market}) "
            f"报告 {len(reports)} 期 → 单季度 {len(metrics)} 期"
        )
        time.sleep(0.5)

    payload["metrics"] = metrics_map
    payload["annual_revenue"] = annual_map
    payload["markets"] = {c.security_id: c.market for c in COMPANIES}
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
