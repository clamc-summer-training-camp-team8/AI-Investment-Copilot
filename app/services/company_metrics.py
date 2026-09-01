"""通用公司定期经营数据采集服务；适配器按公告格式复用。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.ingest.notices import NoticeFetcher, NoticeRecord


@dataclass(frozen=True)
class CompanyMetricObservation:
    metric_id: str
    metric_version: str
    period: str
    value: str
    unit: str
    observation_date: date
    source_document_id: str
    source_url: str
    data_version: str = "company-ir-periodic-v1"


def fetch_periodic_metrics(
    *,
    security_id: str,
    cache_dir: Path,
    limit: int = 24,
) -> list[CompanyMetricObservation]:
    """抓取并解析指定公司的定期公告，不生成缺失值。

    适配器按公告格式工作，不按公司拆分；公司差异由公告元数据和指标
    字典决定。没有匹配公告时返回空列表，由上层显示数据源不可用。
    """
    source = Path(__file__).resolve().parents[2] / "real_data" / "raw" / "announcements.json"
    if not source.exists():
        return []
    announcements = json.loads(source.read_text(encoding="utf-8"))
    rows = [
        item
        for item in announcements
        if item.get("security_id") == security_id
        and any(token in str(item.get("title", "")) for token in ("产销快报", "销量公告", "销量", "月报表"))
    ]
    rows.sort(key=lambda item: str(item.get("disclosure_time", "")), reverse=True)
    fetcher = NoticeFetcher(cache_dir)
    results: list[CompanyMetricObservation] = []
    for item in rows[: max(1, limit)]:
        title = str(item.get("title", ""))
        period = _period_from_title(title)
        if period is None:
            continue
        try:
            notice = fetcher.fetch(
                NoticeRecord(
                    security_id=security_id,
                    security_name=str(item.get("company") or security_id),
                    title=title,
                    notice_date=str(item["disclosure_time"])[:10],
                    detail_url=str(item["url"]),
                )
            )
        except Exception:
            continue
        text = "\n".join(segment.content for segment in notice.parsed.segments)
        sales = _parse_nev_sales(text)
        if sales is not None:
            results.append(
                CompanyMetricObservation(
                    metric_id="AUTO-SALES-M",
                    metric_version="v1.0",
                    period=period,
                    value=str(sales),
                    unit="辆",
                    observation_date=notice.record.published_at.date(),
                    source_document_id=notice.record.document_id,
                    source_url=notice.source_url,
                )
            )
        export_sales = _parse_export_sales(text)
        if export_sales is not None:
            results.append(
                CompanyMetricObservation(
                    metric_id="AUTO-EXPORT-SALES-M",
                    metric_version="v1.0",
                    period=period,
                    value=str(export_sales),
                    unit="辆",
                    observation_date=notice.record.published_at.date(),
                    source_document_id=notice.record.document_id,
                    source_url=notice.source_url,
                )
            )
        battery = _parse_battery_install(text)
        if battery is not None:
            results.append(
                CompanyMetricObservation(
                    metric_id="AUTO-BATTERY-INSTALL-M",
                    metric_version="v1.0",
                    period=period,
                    value=battery,
                    unit="GWh",
                    observation_date=notice.record.published_at.date(),
                    source_document_id=notice.record.document_id,
                    source_url=notice.source_url,
                )
            )
    return results


# 兼容已有调用方；新代码应使用通用函数。
fetch_byd_periodic_metrics = fetch_periodic_metrics


def _period_from_title(title: str) -> str | None:
    """从常见公告标题提取月度期间；无法确认时不生成观测。"""
    match = re.search(r"(20\d{2})年(\d{1,2})月", title)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}"
    match = re.search(r"(20\d{2})[-年](\d{1,2})", title)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}"
    # 港股公告常见“截至31/12/2023”格式。
    match = re.search(r"(?:截至|至)\s*\d{1,2}/(\d{1,2})/(20\d{2})", title)
    if match:
        return f"{match.group(2)}-{int(match.group(1)):02d}"
    return None


def _numbers_after(text: str, marker: str, count: int) -> list[str]:
    match = re.search(marker + r"(.{0,600})", text, re.S)
    if not match:
        return []
    return re.findall(r"\d[\d,]*(?:\.\d+)?", match.group(1))[:count]


def _parse_nev_sales(text: str) -> int | None:
    # 产销快报表格按“产量五列 + 销量五列”排列，新能源汽车销量为第 6 个数。
    values = _numbers_after(text, r"新能源汽车", 10)
    if len(values) < 6:
        return None
    try:
        return int(values[5].replace(",", ""))
    except ValueError:
        return None


def _parse_battery_install(text: str) -> str | None:
    match = re.search(r"动力电池及储能电池装机总量约为\s*([\d.]+)\s*GWh", text)
    return match.group(1) if match else None


def _parse_export_sales(text: str) -> int | None:
    """产销快报中的海外新能源汽车销量（辆）。"""
    match = re.search(r"海外销售新能源汽车(?:合计)?\s*([\d,]+)\s*辆", text)
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None
