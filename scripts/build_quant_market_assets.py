"""从已核验公开行情端点构建不可变 P2 行情、交易日历和公司行动登记簿。"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import cast

from analytics.pipelines.fetch_quotes import HEADERS, TENCENT_URL
from analytics.pipelines.http import request_json
from analytics.pipelines.universe import BENCHMARKS, COMPANIES, Company
from app.core.config import PROJECT_ROOT

VERSION = "tencent-qfq-20260830-v1"
DESTINATION = PROJECT_ROOT / "real_data" / "quant" / VERSION


def _write(path: Path, payload: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return sha256(path.read_bytes()).hexdigest()


def _fetch(target: Company, *, beg: str, end: str) -> list[dict[str, str]]:
    url = TENCENT_URL.format(symbol=target.tencent_symbol, beg=beg, end=end)
    body = request_json(url, headers=HEADERS, attempts=4, base_pause=2.0)
    node = (body.get("data") or {}).get(target.tencent_symbol) or {}
    source_rows = node.get("qfqday") or node.get("day") or []
    rows: list[dict[str, str]] = []
    for item in source_rows:
        if len(item) < 6:
            continue
        close, volume = Decimal(str(item[2])), Decimal(str(item[5]))
        rows.append(
            {
                "trading_date": str(item[0]),
                "adjusted_close": str(close),
                "volume_shares": str(volume),
                "traded_notional": str((close * volume).quantize(Decimal("0.01"))),
            }
        )
    if not rows:
        raise RuntimeError(f"{target.security_id} 未返回行情")
    return rows


def _calendar(open_days: set[str], start: date, end: date) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    current = start
    while current <= end:
        day = current.isoformat()
        rows.append(
            {
                "date": day,
                "is_open": day in open_days,
                "status_source": "provider_benchmark_observation",
            }
        )
        current += timedelta(days=1)
    return rows


def run(*, beg: str, end: str) -> Path:
    if DESTINATION.exists():
        raise FileExistsError(
            f"版本目录已经冻结，禁止原地覆盖: {DESTINATION}；请提升 VERSION 后重建"
        )
    fetched = {company.security_id: _fetch(company, beg=beg, end=end) for company in COMPANIES}
    benchmark_rows = {
        industry: _fetch(benchmark, beg=beg, end=end) for industry, benchmark in BENCHMARKS.items()
    }
    benchmark_by_day = {
        industry: {row["trading_date"]: row["adjusted_close"] for row in rows}
        for industry, rows in benchmark_rows.items()
    }
    bars: list[dict[str, object]] = []
    for company in COMPANIES:
        currency = "HKD" if company.is_hk else "CNY"
        for row in fetched[company.security_id]:
            benchmark_close = benchmark_by_day[company.industry].get(row["trading_date"])
            if benchmark_close is None:
                continue
            bars.append(
                {
                    **row,
                    "security_id": company.security_id,
                    "industry": company.industry,
                    "market": company.market,
                    "currency": currency,
                    "benchmark_id": BENCHMARKS[company.industry].security_id,
                    "benchmark_close": benchmark_close,
                    "market_cap": None,
                    "tradable": True,
                    "limit_up": False,
                    "limit_down": False,
                }
            )
    bars.sort(key=lambda row: (str(row["trading_date"]), str(row["security_id"])))
    if not bars:
        raise RuntimeError("没有可冻结的行情交集")

    start = date.fromisoformat(str(bars[0]["trading_date"]))
    finish = date.fromisoformat(str(bars[-1]["trading_date"]))
    cn_days = {row["trading_date"] for row in benchmark_rows["芯片半导体"]}
    hk_days = {row["trading_date"] for row in fetched["00175"]}
    bars_hash = _write(
        DESTINATION / "bars.json",
        {"schema_version": "portfolio-bars-v1", "data_version": VERSION, "rows": bars},
    )
    calendar_hash = _write(
        DESTINATION / "calendar.json",
        {
            "schema_version": "trading-calendar-v1",
            "data_version": f"{VERSION}-calendar",
            "markets": {
                "A股": _calendar(cast(set[str], cn_days), start, finish),
                "港股": _calendar(cast(set[str], hk_days), start, finish),
            },
        },
    )
    action_hash = _write(
        DESTINATION / "corporate_actions.json",
        {
            "schema_version": "corporate-action-ledger-v1",
            "data_version": f"{VERSION}-corporate-actions",
            "adjustment_contract": "供应商前复权序列已反映除权除息；独立事件只做审计，不重复调整价格",
            "coverage_status": "provider_adjustment_embedded; structured_event_feed_not_available",
            "events": [],
        },
    )
    manifest = {
        "schema_version": "frozen-market-dataset-v1",
        "dataset_id": f"MDS-{VERSION}",
        "data_version": VERSION,
        "status": "frozen",
        "frozen_at": "2026-08-30T00:00:00+08:00",
        "adjustment": "前复权",
        "timezone": "Asia/Shanghai",
        "authorization": {
            "policy_id": "tencent-public-market-research-v1",
            "status": "公开行情研究使用已核验",
            "scope": "项目内部研究、复算与审计；禁止对外再分发",
        },
        "coverage": {"start": start.isoformat(), "end": finish.isoformat()},
        "securities": [company.security_id for company in COMPANIES],
        "assets": {
            "bars": {"path": "bars.json", "sha256": bars_hash},
            "calendar": {"path": "calendar.json", "sha256": calendar_hash},
            "corporate_actions": {
                "path": "corporate_actions.json",
                "sha256": action_hash,
            },
        },
        "capabilities": {
            "adjusted_close": True,
            "trading_calendar": True,
            "suspension_by_missing_session": True,
            "daily_traded_notional": True,
            "capacity_constraint": True,
            "point_in_time_market_cap": False,
            "price_limit_status": False,
            "structured_corporate_action_events": False,
        },
        "limitations": [
            "点时市值未获授权数据覆盖；市值中性运行必须由调用方补充冻结截面，否则硬失败",
            "涨跌停状态无独立字段；当前资产不得声称完成涨跌停可成交性模拟",
            "前复权已隐含公司行动效果，但结构化公司行动事件源尚无覆盖，登记簿明确为空",
            "港股为 HKD、基准为 CNY；未冻结 FX 时不得把混币种超额收益解释为 Alpha",
        ],
    }
    _write(DESTINATION / "manifest.json", manifest)
    print(f"冻结行情 {len(bars)} 行 → {DESTINATION}")
    return DESTINATION


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--beg", default="2023-12-01")
    parser.add_argument("--end", default="2026-08-09")
    args = parser.parse_args()
    run(beg=args.beg, end=args.end)


if __name__ == "__main__":
    main()
