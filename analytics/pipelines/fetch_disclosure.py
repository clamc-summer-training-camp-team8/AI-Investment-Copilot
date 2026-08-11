"""A 类管道：公告采集。

从巨潮资讯网抓公告清单，落到 `real_data/raw/`（已纳入版本控制，见 ADR-0006：
这些是强制公开披露的信息，提交它们是为了让团队复算同一批数字）。

五条与合规和数据质量直接相关的约定：

1. **披露时间用接口返回的时间戳，不用抓取时间。** 这是 DQ-001 的字段，也是收益
   窗口的起点。用抓取时间兜底会直接造成未来信息泄露。
2. **按公司分片落盘。** 九家公司约 180 次翻页请求，中途失败时已成功的公司不需要
   重抓。原来是全部抓完才写一次，任何一家失败就全丢。
3. **限速 + 指数退避重试。** 公开接口，加间隔避免给对方造成压力；上游偶发断连时
   退避重试，而不是让整轮采集崩掉。
4. **按 announcement_id 去重。** 巨潮翻页边界会重复返回同一条公告，不去重会让
   同一事件在评测里被计两次。
5. **港股与 A 股走不同的 column。** 港股 column=hke 且 orgId 取自 hke_stock.json，
   用 A 股的 szse 查港股代码会返回别的公司。

用法：
    python -m analytics.pipelines.fetch_disclosure
    python -m analytics.pipelines.fetch_disclosure --pages 20 --refresh
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from analytics.pipelines.http import cached_shard, request_json
from analytics.pipelines.universe import COMPANIES, Company
from app.core.config import PROJECT_ROOT
from app.core.timeutil import BUSINESS_TZ

RAW_DIR = PROJECT_ROOT / "real_data" / "raw"
SHARD_DIR = RAW_DIR / "announcements"
QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (research-tooling; MVP validation)",
    "Referer": "http://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}
REQUEST_INTERVAL_SEC = 0.8
DATA_VERSION = "cninfo-announcement-v2"


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
    market: str = "A股"
    industry: str = ""


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
    seen: set[str] = set()

    for page in range(1, max_pages + 1):
        payload = urlencode(
            {
                "pageNum": str(page),
                "pageSize": str(page_size),
                "column": "hke" if company.is_hk else "szse",
                "tabName": "fulltext",
                "stock": f"{company.security_id},{company.org_id}",
                "seDate": f"{start}~{end}",
                "sortName": "time",
                "sortType": "desc",
                "isHLtitle": "true",
            }
        ).encode("utf-8")

        body = request_json(QUERY_URL, data=payload, headers=HEADERS)
        announcements = body.get("announcements")
        if not announcements:
            break

        for item in announcements:
            timestamp = item.get("announcementTime")
            if not timestamp:
                # 披露时间为空是阻断级错误（DQ-001），不入样本、不猜时间
                continue
            announcement_id = str(item.get("announcementId") or "")
            if announcement_id in seen:
                # 翻页边界重复，不是新事件
                continue
            seen.add(announcement_id)

            moment = datetime.fromtimestamp(int(timestamp) / 1000, tz=BUSINESS_TZ)
            results.append(
                Announcement(
                    announcement_id=announcement_id,
                    security_id=company.security_id,
                    company=company.name,
                    title=str(item.get("announcementTitle") or "").strip(),
                    disclosure_time=moment.isoformat(),
                    url=("http://static.cninfo.com.cn/" + str(item.get("adjunctUrl") or "")),
                    doc_type=str(item.get("columnName") or ""),
                    market=company.market,
                    industry=company.industry,
                )
            )

        if not body.get("hasMore"):
            break
        time.sleep(REQUEST_INTERVAL_SEC)

    return results


def run(*, start: str, end: str, max_pages: int, refresh: bool = False) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    everything: list[Announcement] = []

    for company in COMPANIES:
        shard = SHARD_DIR / f"{company.security_id}.json"

        def build(c: Company = company) -> list[dict[str, object]]:
            items = fetch_company(c, start=start, end=end, max_pages=max_pages)
            time.sleep(REQUEST_INTERVAL_SEC)
            return [asdict(a) for a in items]

        rows = cached_shard(shard, build, refresh=refresh, label=company.name)
        print(f"{company.industry}/{company.name}({company.security_id}) 公告 {len(rows)} 条")
        everything.extend(Announcement(**row) for row in rows)

    # 跨公司再去一次重，然后按披露时间排序，便于后续按时间切分样本内外
    unique: dict[str, Announcement] = {}
    for item in everything:
        unique.setdefault(item.announcement_id, item)
    ordered = sorted(unique.values(), key=lambda a: a.disclosure_time)

    dropped = len(everything) - len(ordered)
    if dropped:
        print(f"去重丢弃 {dropped} 条重复公告")

    target = RAW_DIR / "announcements.json"
    target.write_text(
        json.dumps([asdict(a) for a in ordered], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"合计 {len(ordered)} 条 → {target}")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2026-08-09")
    parser.add_argument("--pages", type=int, default=20)
    parser.add_argument("--refresh", action="store_true", help="忽略分片缓存重新抓取")
    args = parser.parse_args()
    run(start=args.start, end=args.end, max_pages=args.pages, refresh=args.refresh)


if __name__ == "__main__":
    main()
