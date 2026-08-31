"""B/C 类管道：行情采集，供 20 日超额收益标签使用。

取前复权收盘价（`fqt=1`）。复权方式属于 GAP-003 未决项，这里固定用前复权并记录在
数据版本里——口径可以待确认，但**不能每次跑用不同口径**，那样结果不可复算。

同时取三个行业基准。基准事前确定（说明书 10.3），选定后不换。跨行业不能共用
一个基准，否则算出来的「超额」里混着行业轮动。

**数据源换成腾讯。** 东财的 kline 接口在本环境直接拒连（RemoteDisconnected），
换 host、换 UA、加指数退避全部无效——不是限流，是被拒。腾讯的同一类接口覆盖
A 股、港股与三个基准指数，且支持前复权，因此作为主源。东财保留为备源：
主源某个标的取不到时自动回退，两个源都取不到才算失败。

按标的分片落盘：抓失败的标的下次单独补，已抓到的不重来。

用法：
    python -m analytics.pipelines.fetch_quotes
    python -m analytics.pipelines.fetch_quotes --refresh
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from analytics.pipelines.http import FetchError, cached_shard, request_json
from analytics.pipelines.universe import Company, all_quote_targets
from app.core.config import PROJECT_ROOT

RAW_DIR = PROJECT_ROOT / "real_data" / "raw"
SHARD_DIR = RAW_DIR / "quotes"
TENCENT_URL = (
    "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get" "?param={symbol},day,{beg},{end},1000,qfq"
)
EASTMONEY_URL = (
    "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    "?secid={secid}&fields1=f1,f2,f3&fields2=f51,f53&klt=101&fqt=1"
    "&beg={beg}&end={end}&lmt=100000"
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/126.0 Safari/537.36",
    "Referer": "https://gu.qq.com/",
}
DATA_VERSION = "tencent-qfq-v1"
REQUEST_INTERVAL_SEC = 1.5


def _from_tencent(target: Company, *, beg: str, end: str) -> dict[str, str]:
    """腾讯前复权日线。返回结构是 {symbol: {qfqday: [[日期, 开, 收, 高, 低, 量], ...]}}。"""
    symbol = target.tencent_symbol
    url = TENCENT_URL.format(symbol=symbol, beg=beg, end=end)
    body = request_json(url, headers=HEADERS, attempts=4, base_pause=2.0)

    node = (body.get("data") or {}).get(symbol) or {}
    rows = node.get("qfqday") or node.get("day") or []
    series: dict[str, str] = {}
    for row in rows:
        if len(row) >= 3:
            # 索引 2 是收盘价，索引 1 是开盘价。取错会让收益算成开盘到开盘。
            series[str(row[0])] = str(row[2])
    return series


def _from_eastmoney(target: Company, *, beg: str, end: str) -> dict[str, str]:
    """东财前复权日线，作为备源。日期格式与腾讯不同：YYYYMMDD。"""
    url = EASTMONEY_URL.format(
        secid=target.secid, beg=beg.replace("-", ""), end=end.replace("-", "")
    )
    body = request_json(url, headers=HEADERS, attempts=2, base_pause=2.0)
    klines = (body.get("data") or {}).get("klines") or []
    series: dict[str, str] = {}
    for row in klines:
        parts = str(row).split(",")
        if len(parts) >= 2:
            series[parts[0]] = parts[1]
    return series


def fetch_series(target: Company, *, beg: str, end: str) -> dict[str, str]:
    """返回 {交易日: 前复权收盘价}。只取日线收盘价，不做任何平滑。

    主源腾讯，备源东财。两个源都空才算失败——空行情不能静默返回，
    下游会把「抓不到」当成「这只票没有交易」。
    """
    series = _from_tencent(target, beg=beg, end=end)
    if series:
        return series

    print(f"    {target.name} 主源为空，回退备源")
    series = _from_eastmoney(target, beg=beg, end=end)
    if series:
        return series

    raise FetchError(f"{target.name}({target.tencent_symbol}) 两个源都取不到行情")


def run(*, beg: str, end: str, refresh: bool = False) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    series_map: dict[str, dict[str, str]] = {}
    failed: list[str] = []

    for target in all_quote_targets():
        shard = SHARD_DIR / f"{target.secid.replace('.', '_')}.json"

        def build(t: Company = target) -> dict[str, str]:
            data = fetch_series(t, beg=beg, end=end)
            time.sleep(REQUEST_INTERVAL_SEC)
            return data

        try:
            data = cached_shard(shard, build, refresh=refresh, label=target.name)
        except FetchError as exc:
            # 缺哪个标的要说清楚：缺基准意味着整个行业算不出超额收益，
            # 静默跳过会让下游把「抓不到」当成「没有行情」。
            print(f"  {target.name}({target.secid}) 抓取失败：{exc}")
            failed.append(f"{target.name}({target.secid})")
            continue

        series_map[target.security_id] = data
        print(f"{target.name}({target.security_id}) 交易日 {len(data)} 天")

    payload: dict[str, object] = {
        "data_version": DATA_VERSION,
        "adjust": "前复权",
        "series": series_map,
    }
    destination = RAW_DIR / "quotes.json"
    destination.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"→ {destination}")
    if failed:
        print(f"以下标的未抓到，收益标签会缺失：{'、'.join(failed)}")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--beg", default="2023-12-01")
    parser.add_argument("--end", default="2026-08-09")
    parser.add_argument("--refresh", action="store_true", help="忽略分片缓存重新抓取")
    args = parser.parse_args()
    run(beg=args.beg, end=args.end, refresh=args.refresh)


if __name__ == "__main__":
    main()
