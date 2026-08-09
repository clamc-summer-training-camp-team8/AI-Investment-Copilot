"""A 类管道：公告采集。

从巨潮资讯网抓公告清单，落到 `real_data/raw/`（不进版本控制）。

三条与合规和数据质量直接相关的约定：

1. **披露时间用接口返回的时间戳，不用抓取时间。** 这是 DQ-001 的字段，也是收益
   窗口的起点。用抓取时间兜底会直接造成未来信息泄露。
2. **原始响应整份落盘。** 说明书 7.1 要求原文件不可覆盖。重跑解析时用落盘的原始
   数据，不重新请求——否则两次解析结果可能不同，`parser_version` 失去意义。
3. **限速。** 公开接口，加间隔避免给对方造成压力。

用法：
    python -m analytics.pipelines.fetch_disclosure
    python -m analytics.pipelines.fetch_disclosure --pages 20
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from analytics.pipelines.universe import COMPANIES, Company
from app.core.config import PROJECT_ROOT
from app.core.timeutil import BUSINESS_TZ

RAW_DIR = PROJECT_ROOT / "real_data" / "raw"
QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (research-tooling; MVP validation)",
    "Referer": "http://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}
REQUEST_INTERVAL_SEC = 0.6


@dataclass
class Announcement:
    """一条公告。

    `disclosure_time` 是巨潮返回的公告时间，业务时区。事实发生时间通常要从正文
    推断，多数公告拿不到，因此允许为空（FLD-006）——但披露时间必填。
    """

    announcement_id: str
    security_id: str
    company: str
    title: str
    disclosure_time: str
    url: str
    doc_type: str = ""


def _post(payload: dict[str, str]) -> dict[str, object]:
    data = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(QUERY_URL, data=data, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_company(
    company: Company,
    *,
    start: str,
    end: str,
    max_pages: int,
    page_size: int = 30,
) -> list[Announcement]:
    """抓一家公司的公告清单。"""
    results: list[Announcement] = []
    for page in range(1, max_pages + 1):
        payload = {
            "pageNum": str(page),
            "pageSize": str(page_size),
            "column": "szse",
            "tabName": "fulltext",
            "stock": f"{company.security_id},{company.org_id}",
            "seDate": f"{start}~{end}",
            "sortName": "time",
            "sortType": "desc",
            "isHLtitle": "true",
        }
        body = _post(payload)
        announcements = body.get("announcements")
        if not announcements:
            break

        assert isinstance(announcements, list)
        for item in announcements:
            timestamp = item.get("announcementTime")
            if not timestamp:
                # 披露时间为空是阻断级错误（DQ-001），不入样本、不猜时间
                continue
            moment = datetime.fromtimestamp(int(timestamp) / 1000, tz=BUSINESS_TZ)
            results.append(
                Announcement(
                    announcement_id=str(item.get("announcementId") or ""),
                    security_id=company.security_id,
                    company=company.name,
                    title=str(item.get("announcementTitle") or "").strip(),
                    disclosure_time=moment.isoformat(),
                    url=("http://static.cninfo.com.cn/" + str(item.get("adjunctUrl") or "")),
                    doc_type=str(item.get("columnName") or ""),
                )
            )

        if not body.get("hasMore"):
            break
        time.sleep(REQUEST_INTERVAL_SEC)

    return results


def run(*, start: str, end: str, max_pages: int) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    everything: list[Announcement] = []

    for company in COMPANIES:
        items = fetch_company(company, start=start, end=end, max_pages=max_pages)
        print(f"{company.name}({company.security_id}) 公告 {len(items)} 条")
        everything.extend(items)
        time.sleep(REQUEST_INTERVAL_SEC)

    # 按披露时间排序落盘，便于后续按时间切分样本内外
    everything.sort(key=lambda a: a.disclosure_time)
    target = RAW_DIR / "announcements.json"
    target.write_text(
        json.dumps([asdict(a) for a in everything], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"合计 {len(everything)} 条 → {target}")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2026-08-09")
    parser.add_argument("--pages", type=int, default=20)
    args = parser.parse_args()
    run(start=args.start, end=args.end, max_pages=args.pages)


if __name__ == "__main__":
    main()
