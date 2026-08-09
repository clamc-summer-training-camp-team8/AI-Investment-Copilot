"""B/C 类管道：行情采集，供 20 日超额收益标签使用。

取前复权收盘价（`fqt=1`）。复权方式属于 GAP-003 未决项，这里固定用前复权并记录在
数据版本里——口径可以待确认，但**不能每次跑用不同口径**，那样结果不可复算。

同时取基准（创业板指）。基准事前确定（说明书 10.3），选定后不换。

用法：
    python -m analytics.pipelines.fetch_quotes
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

from analytics.pipelines.universe import BENCHMARK, COMPANIES, Company
from app.core.config import PROJECT_ROOT

RAW_DIR = PROJECT_ROOT / "real_data" / "raw"
KLINE_URL = (
    "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    "?secid={secid}&fields1=f1,f2,f3&fields2=f51,f53&klt=101&fqt=1"
    "&beg={beg}&end={end}&lmt=100000"
)
HEADERS = {"User-Agent": "Mozilla/5.0 (research-tooling; MVP validation)"}
DATA_VERSION = "em-qfq-v1"


def fetch_series(target: Company, *, beg: str, end: str) -> dict[str, str]:
    """返回 {交易日: 前复权收盘价}。只取日线收盘价，不做任何平滑。"""
    url = KLINE_URL.format(secid=target.secid, beg=beg, end=end)
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))

    klines = (body.get("data") or {}).get("klines") or []
    series: dict[str, str] = {}
    for row in klines:
        parts = str(row).split(",")
        if len(parts) >= 2:
            series[parts[0]] = parts[1]
    return series


def run(*, beg: str, end: str) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {"data_version": DATA_VERSION, "adjust": "前复权", "series": {}}
    series_map: dict[str, dict[str, str]] = {}

    for target in (*COMPANIES, BENCHMARK):
        data = fetch_series(target, beg=beg, end=end)
        series_map[target.security_id] = data
        print(f"{target.name}({target.security_id}) 交易日 {len(data)} 天")
        time.sleep(0.4)

    payload["series"] = series_map
    destination = RAW_DIR / "quotes.json"
    destination.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"→ {destination}")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--beg", default="20231201")
    parser.add_argument("--end", default="20260809")
    args = parser.parse_args()
    run(beg=args.beg, end=args.end)


if __name__ == "__main__":
    main()
