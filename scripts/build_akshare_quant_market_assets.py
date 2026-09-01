"""以 AKShare 为主源、Tushare 为可选补充源构建不可变量化行情。"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import partial
from hashlib import sha256
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

from analytics.pipelines.quant_price_limit_derivations import (
    QuantPriceLimitDerivationSet,
)
from analytics.pipelines.universe import BENCHMARKS, COMPANIES, Company
from app.ingest.market_reference_cache import (
    MarketCapCacheLoad,
    PriceLimitCacheLoad,
    TradingCalendarCacheLoad,
    load_market_cap_cache,
    load_price_limit_cache,
    load_trading_calendar_cache,
)
from app.ingest.market_source_retry import MarketRetryEvent, call_market_source
from app.ingest.market_source_secrets import (
    read_tushare_credentials_file,
    validate_tushare_api_url,
)
from app.ingest.market_sources import (
    AksharePrimarySource,
    MarketSourceError,
    PointInTimeSupplement,
    SourceQuote,
    TushareSupplementSource,
)

DEFAULT_VERSION = "akshare-qfq-tushare120-20260830-v1"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PERMISSION_REPORT = (
    PROJECT_ROOT / ".runtime" / "governance" / "tushare-permission-probe.json"
)
DEFAULT_REFERENCE_CACHE_ROOT = PROJECT_ROOT / ".runtime" / "quant-reference-cache"

QUALITY_THRESHOLDS = {
    "overlap_ratio": Decimal("0.995"),
    "close_relative_error": Decimal("0.0001"),
    "volume_relative_error": Decimal("0.001"),
    "notional_relative_error": Decimal("0.001"),
}


def _write(path: Path, payload: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return sha256(path.read_bytes()).hexdigest()


def _calendar(
    open_days: set[str], start: date, end: date, *, source: str
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    current = start
    while current <= end:
        day = current.isoformat()
        rows.append({"date": day, "is_open": day in open_days, "status_source": source})
        current += timedelta(days=1)
    return rows


def _validate_quotes(target: Company, rows: list[SourceQuote]) -> None:
    if len(rows) < 30:
        raise MarketSourceError(f"{target.security_id} 行情不足 30 个交易日")
    for row in rows:
        if row.adjusted_high < max(row.adjusted_open, row.adjusted_close, row.adjusted_low):
            raise MarketSourceError(f"{target.security_id} {row.trading_date}: 最高价小于其他价格")
        if row.adjusted_low > min(row.adjusted_open, row.adjusted_close, row.adjusted_high):
            raise MarketSourceError(f"{target.security_id} {row.trading_date}: 最低价大于其他价格")
        if row.volume_shares is not None and row.volume_shares < 0:
            raise MarketSourceError(f"{target.security_id} {row.trading_date}: 成交量为负")
        if row.traded_notional is not None and row.traded_notional < 0:
            raise MarketSourceError(f"{target.security_id} {row.trading_date}: 成交额为负")


def _raw_row(target: Company, quote: SourceQuote, *, role: str) -> dict[str, object]:
    return {
        "trading_date": quote.trading_date,
        "security_id": target.security_id,
        "role": role,
        "market": target.market,
        "adjusted_open": quote.adjusted_open,
        "adjusted_close": quote.adjusted_close,
        "adjusted_high": quote.adjusted_high,
        "adjusted_low": quote.adjusted_low,
        "volume_shares": quote.volume_shares,
        "traded_notional": quote.traded_notional,
        "source_interface": quote.source_interface,
        "upstream_provider": quote.upstream_provider,
    }


def _relative_error(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None or right is None:
        return None
    return abs(left - right) / max(abs(left), abs(right), Decimal(1))


def _cross_source_quality(
    target: Company,
    primary: list[SourceQuote],
    supplement: list[SourceQuote],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    primary_by_day = {item.trading_date: item for item in primary}
    supplement_by_day = {item.trading_date: item for item in supplement}
    all_days = sorted(primary_by_day.keys() | supplement_by_day.keys())
    overlap = sorted(primary_by_day.keys() & supplement_by_day.keys())
    denominator = max(len(primary_by_day), len(supplement_by_day), 1)
    overlap_ratio = Decimal(len(overlap)) / Decimal(denominator)
    metrics = {
        "close": (
            "adjusted_close",
            QUALITY_THRESHOLDS["close_relative_error"],
        ),
        "volume": (
            "volume_shares",
            QUALITY_THRESHOLDS["volume_relative_error"],
        ),
        "notional": (
            "traded_notional",
            QUALITY_THRESHOLDS["notional_relative_error"],
        ),
    }
    metric_report: dict[str, object] = {}
    for label, (attribute, threshold) in metrics.items():
        errors = [
            _relative_error(
                cast(Decimal | None, getattr(primary_by_day[day], attribute)),
                cast(Decimal | None, getattr(supplement_by_day[day], attribute)),
            )
            for day in overlap
        ]
        comparable = [value for value in errors if value is not None]
        metric_report[label] = {
            "comparable_rows": len(comparable),
            "threshold": threshold,
            "mismatch_rows": sum(value > threshold for value in comparable),
            "max_relative_error": max(comparable, default=None),
        }
    passed = overlap_ratio >= QUALITY_THRESHOLDS["overlap_ratio"] and all(
        cast(int, cast(dict[str, object], item)["mismatch_rows"]) == 0
        for item in metric_report.values()
    )
    snapshot = []
    for day in all_days:
        left = primary_by_day.get(day)
        right = supplement_by_day.get(day)
        snapshot.append(
            {
                "security_id": target.security_id,
                "trading_date": day,
                "akshare_raw_close": left.adjusted_close if left else None,
                "akshare_volume_shares": left.volume_shares if left else None,
                "akshare_traded_notional": left.traded_notional if left else None,
                "tushare_raw_close": right.adjusted_close if right else None,
                "tushare_volume_shares": right.volume_shares if right else None,
                "tushare_traded_notional": right.traded_notional if right else None,
            }
        )
    return (
        {
            "security_id": target.security_id,
            "akshare_rows": len(primary_by_day),
            "tushare_rows": len(supplement_by_day),
            "overlap_rows": len(overlap),
            "overlap_ratio": overlap_ratio,
            "metrics": metric_report,
            "passed": passed,
        },
        snapshot,
    )


def _apply_price_limit_derivations(
    derivation_set: QuantPriceLimitDerivationSet | None,
    *,
    companies: tuple[Company, ...],
    start: date,
    end: date,
    cross_source_snapshot: list[dict[str, object]],
    observed_price_limits: PriceLimitCacheLoad,
    supplements: dict[str, dict[date, PointInTimeSupplement]],
) -> int:
    if derivation_set is None:
        return 0
    company_ids = {company.security_id for company in companies if not company.is_hk}
    snapshots = {
        (str(row["security_id"]), cast(date, row["trading_date"])): row
        for row in cross_source_snapshot
    }
    by_security: dict[str, list[dict[str, object]]] = {}
    for row in cross_source_snapshot:
        by_security.setdefault(str(row["security_id"]), []).append(row)
    for rows in by_security.values():
        rows.sort(key=lambda row: cast(date, row["trading_date"]))

    for item in derivation_set.rows:
        if item.security_id not in company_ids:
            raise MarketSourceError(f"涨跌停推导证券不在当前研究池: {item.security_id}")
        if item.trading_date < start or item.trading_date > end:
            raise MarketSourceError(
                f"涨跌停推导日不在构建区间: {item.security_id} {item.trading_date}"
            )
        if item.trading_date in observed_price_limits.by_security.get(item.security_id, {}):
            raise MarketSourceError(
                f"涨跌停直接观测已存在，禁止规则推导覆盖: "
                f"{item.security_id} {item.trading_date}"
            )
        snapshot = snapshots.get((item.security_id, item.trading_date))
        if snapshot is None:
            raise MarketSourceError(
                f"涨跌停推导缺少当日双源行情: {item.security_id} {item.trading_date}"
            )
        akshare_close = Decimal(str(snapshot.get("akshare_raw_close")))
        tushare_close = Decimal(str(snapshot.get("tushare_raw_close")))
        akshare_notional = Decimal(str(snapshot.get("akshare_traded_notional")))
        tushare_notional = Decimal(str(snapshot.get("tushare_traded_notional")))
        if akshare_close != item.close or tushare_close != item.close:
            raise MarketSourceError(f"涨跌停推导收盘价与双源快照不一致: {item.security_id}")
        akshare_notional_error = _relative_error(akshare_notional, item.traded_notional)
        tushare_notional_error = _relative_error(tushare_notional, item.traded_notional)
        if (
            akshare_notional_error is None
            or tushare_notional_error is None
            or akshare_notional_error > QUALITY_THRESHOLDS["notional_relative_error"]
            or tushare_notional_error > QUALITY_THRESHOLDS["notional_relative_error"]
        ):
            raise MarketSourceError(f"涨跌停推导成交额与双源快照不一致: {item.security_id}")
        previous_rows = [
            row
            for row in by_security.get(item.security_id, [])
            if cast(date, row["trading_date"]) < item.trading_date
        ]
        if not previous_rows:
            raise MarketSourceError(f"涨跌停推导缺少前一交易日: {item.security_id}")
        previous = previous_rows[-1]
        if (
            Decimal(str(previous.get("akshare_raw_close"))) != item.pre_close
            or Decimal(str(previous.get("tushare_raw_close"))) != item.pre_close
        ):
            raise MarketSourceError(f"涨跌停推导前收盘与双源快照不一致: {item.security_id}")
        company_supplements = supplements.setdefault(item.security_id, {})
        cached = company_supplements.get(item.trading_date, PointInTimeSupplement())
        if cached.price_limit_observed:
            raise MarketSourceError(f"涨跌停直接观测已加载，禁止推导覆盖: {item.security_id}")
        company_supplements[item.trading_date] = PointInTimeSupplement(
            market_cap=cached.market_cap,
            tradable=cached.tradable,
            limit_up=item.limit_up,
            limit_down=item.limit_down,
            market_cap_observed=cached.market_cap_observed,
            price_limit_observed=False,
            price_limit_derived=True,
        )
    return len(derivation_set.rows)


def load_tushare_permission_profile(
    path: Path,
) -> tuple[frozenset[str], dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "tushare-permission-probe-v1":
        raise MarketSourceError("Tushare 权限探测报告版本不受支持")
    endpoints = payload.get("endpoints")
    if not isinstance(endpoints, list):
        raise MarketSourceError("Tushare 权限探测报告缺少 endpoints")
    available = frozenset(
        str(item.get("endpoint"))
        for item in endpoints
        if isinstance(item, dict) and item.get("status") in {"available", "available_empty"}
    )
    if "daily" not in available:
        raise MarketSourceError("Tushare daily 未实测可用，不能启用跨源冻结")
    return available, cast(dict[str, object], payload)


def _fetch_equity(
    primary: AksharePrimarySource,
    supplement: TushareSupplementSource | None,
    target: Company,
    *,
    start: date,
    end: date,
    fallback_enabled: bool,
    max_attempts: int,
    retry_delay_seconds: float,
    retry_events: list[MarketRetryEvent],
    secrets: tuple[str, ...],
) -> tuple[list[SourceQuote], bool, str | None]:
    try:
        rows = call_market_source(
            f"akshare.equity.{target.security_id}",
            lambda: primary.equity_quotes(target, start=start, end=end),
            max_attempts=max_attempts,
            wait_seconds=retry_delay_seconds,
            secrets=secrets,
            events=retry_events,
        )
        _validate_quotes(target, rows)
        return rows, False, None
    except MarketSourceError as primary_error:
        if supplement is None or target.is_hk or not fallback_enabled:
            raise
        rows = call_market_source(
            f"tushare.pro_bar.{target.security_id}",
            lambda: supplement.fallback_a_share_quotes(target, start=start, end=end),
            max_attempts=max_attempts,
            wait_seconds=retry_delay_seconds,
            secrets=secrets,
            events=retry_events,
        )
        _validate_quotes(target, rows)
        return rows, True, str(primary_error)


def run(
    *,
    start: date,
    end: date,
    version: str = DEFAULT_VERSION,
    tushare_token: str | None = None,
    tushare_api_url: str | None = None,
    tushare_endpoints: frozenset[str] = frozenset(),
    permission_profile: dict[str, object] | None = None,
    reference_cache_root: Path | None = None,
    max_attempts: int = 3,
    retry_delay_seconds: float = 1.0,
    companies: tuple[Company, ...] = COMPANIES,
    benchmarks_by_industry: dict[str, Company] | None = None,
    fetch_structured_actions: bool = False,
    governance_assets: dict[str, dict[str, object]] | None = None,
    historical_controls: tuple[dict[str, object], ...] = (),
    price_limit_derivation_set: QuantPriceLimitDerivationSet | None = None,
) -> Path:
    selected_benchmarks = BENCHMARKS if benchmarks_by_industry is None else benchmarks_by_industry
    if not companies:
        raise MarketSourceError("冻结行情至少需要一只证券")
    if len({company.security_id for company in companies}) != len(companies):
        raise MarketSourceError("冻结行情证券代码重复")
    missing_benchmarks = sorted(
        {company.industry for company in companies} - set(selected_benchmarks)
    )
    if missing_benchmarks:
        raise MarketSourceError(f"研究行业缺少事前基准: {', '.join(missing_benchmarks)}")
    invalid_governance_assets = sorted(
        key
        for key in (governance_assets or {})
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key)
    )
    if invalid_governance_assets:
        raise MarketSourceError(
            "治理资产名称只能使用小写字母、数字和下划线: "
            + ", ".join(invalid_governance_assets)
        )
    destination = PROJECT_ROOT / "real_data" / "quant" / version
    if destination.exists():
        raise FileExistsError(
            f"版本目录已经冻结，禁止原地覆盖: {destination}；请提升 --version 后重建"
        )
    retry_events: list[MarketRetryEvent] = []
    secrets = (tushare_token,) if tushare_token else ()
    primary = call_market_source(
        "akshare.initialize",
        AksharePrimarySource,
        max_attempts=max_attempts,
        wait_seconds=retry_delay_seconds,
        secrets=secrets,
        events=retry_events,
    )
    supplement = (
        call_market_source(
            "tushare.initialize",
            lambda: TushareSupplementSource(tushare_token, api_url=tushare_api_url),
            max_attempts=max_attempts,
            wait_seconds=retry_delay_seconds,
            secrets=secrets,
            events=retry_events,
        )
        if tushare_token
        else None
    )
    market_cap_cache = (
        load_market_cap_cache(reference_cache_root, start=start, end=end)
        if reference_cache_root is not None
        else MarketCapCacheLoad({}, (), 0)
    )
    trading_calendar_cache = (
        load_trading_calendar_cache(reference_cache_root, start=start, end=end)
        if reference_cache_root is not None
        else TradingCalendarCacheLoad(frozenset(), frozenset(), ())
    )
    price_limit_cache = (
        load_price_limit_cache(reference_cache_root, start=start, end=end)
        if reference_cache_root is not None
        else PriceLimitCacheLoad({}, (), 0)
    )

    equity: dict[str, list[SourceQuote]] = {}
    benchmarks: dict[str, list[SourceQuote]] = {}
    supplements: dict[str, dict[date, PointInTimeSupplement]] = {
        security_id: {
            trading_date: PointInTimeSupplement(
                market_cap=market_cap,
                market_cap_observed=True,
            )
            for trading_date, market_cap in observations.items()
        }
        for security_id, observations in market_cap_cache.by_security.items()
    }
    for security_id, observations in price_limit_cache.by_security.items():
        company_supplements = supplements.setdefault(security_id, {})
        for trading_date, observation in observations.items():
            cached = company_supplements.get(trading_date, PointInTimeSupplement())
            company_supplements[trading_date] = PointInTimeSupplement(
                market_cap=cached.market_cap,
                tradable=cached.tradable,
                limit_up=observation.limit_up,
                limit_down=observation.limit_down,
                market_cap_observed=cached.market_cap_observed,
                price_limit_observed=True,
            )
    supplement_errors: dict[str, list[str]] = {}
    quality_by_security: list[dict[str, object]] = []
    cross_source_snapshot: list[dict[str, object]] = []
    fallback_reasons: dict[str, str] = {}
    fallback_count = 0
    source_counts: Counter[str] = Counter()

    for company in companies:
        rows, used_fallback, reason = _fetch_equity(
            primary,
            supplement,
            company,
            start=start,
            end=end,
            fallback_enabled="pro_bar" in tushare_endpoints,
            max_attempts=max_attempts,
            retry_delay_seconds=retry_delay_seconds,
            retry_events=retry_events,
            secrets=secrets,
        )
        equity[company.security_id] = rows
        if used_fallback:
            fallback_count += 1
            fallback_reasons[company.security_id] = reason or "AKShare 主源不可用"
        if supplement is not None and not company.is_hk:
            # 参考字段受配额约束，只能由独立缓存任务调用。
            # 主构建只消费已验哈希缓存，不得按证券重复消耗接口频次。
            batch = supplement.a_share_supplements(
                company,
                start=start,
                end=end,
                enabled_endpoints=tushare_endpoints - {"daily_basic", "trade_cal", "stk_limit"},
            )
            company_supplements = supplements.setdefault(company.security_id, {})
            for trading_date, observed in batch.by_date.items():
                cached = company_supplements.get(trading_date, PointInTimeSupplement())
                use_observed_price_limit = observed.price_limit_observed
                company_supplements[trading_date] = PointInTimeSupplement(
                    market_cap=(
                        cached.market_cap if cached.market_cap_observed else observed.market_cap
                    ),
                    tradable=observed.tradable,
                    limit_up=(
                        observed.limit_up if use_observed_price_limit else cached.limit_up
                    ),
                    limit_down=(
                        observed.limit_down if use_observed_price_limit else cached.limit_down
                    ),
                    market_cap_observed=(
                        cached.market_cap_observed or observed.market_cap_observed
                    ),
                    price_limit_observed=(
                        cached.price_limit_observed or observed.price_limit_observed
                    ),
                    price_limit_derived=(
                        False if use_observed_price_limit else cached.price_limit_derived
                    ),
                )
            if batch.errors:
                supplement_errors[company.security_id] = list(batch.errors)
            if "daily" in tushare_endpoints and not used_fallback:
                akshare_raw = call_market_source(
                    f"akshare.raw.{company.security_id}",
                    partial(primary.a_share_raw_quotes, company, start=start, end=end),
                    max_attempts=max_attempts,
                    wait_seconds=retry_delay_seconds,
                    secrets=secrets,
                    events=retry_events,
                )
                tushare_raw = call_market_source(
                    f"tushare.daily.{company.security_id}",
                    partial(
                        supplement.daily_a_share_quotes,
                        company,
                        start=start,
                        end=end,
                    ),
                    max_attempts=max_attempts,
                    wait_seconds=retry_delay_seconds,
                    secrets=secrets,
                    events=retry_events,
                )
                quality, snapshot = _cross_source_quality(company, akshare_raw, tushare_raw)
                quality_by_security.append(quality)
                cross_source_snapshot.extend(snapshot)

    derived_price_limit_count = _apply_price_limit_derivations(
        price_limit_derivation_set,
        companies=companies,
        start=start,
        end=end,
        cross_source_snapshot=cross_source_snapshot,
        observed_price_limits=price_limit_cache,
        supplements=supplements,
    )

    historical_control_rows: list[dict[str, object]] = []
    historical_control_coverage: list[dict[str, object]] = []
    for item in historical_controls:
        security_id = str(item["security_id"])
        listed_from = date.fromisoformat(str(item["listed_from"]))
        listed_to = date.fromisoformat(str(item["listed_to"]))
        control_start = max(start, listed_from)
        control_end = min(end, listed_to)
        if control_start > control_end:
            raise MarketSourceError(f"退市对照样本与构建区间无交集: {security_id}")
        control = Company(
            security_id=security_id,
            name=security_id,
            org_id="",
            secid=f"{'1' if security_id.startswith('6') else '0'}.{security_id}",
            industry="历史退市对照",
            role="退市生存者偏差对照",
        )
        rows, used_fallback, reason = _fetch_equity(
            primary,
            supplement,
            control,
            start=control_start,
            end=control_end,
            fallback_enabled="pro_bar" in tushare_endpoints,
            max_attempts=max_attempts,
            retry_delay_seconds=retry_delay_seconds,
            retry_events=retry_events,
            secrets=secrets,
        )
        if used_fallback:
            fallback_count += 1
            fallback_reasons[security_id] = reason or "AKShare 主源不可用"
        historical_control_rows.extend(
            {
                **_raw_row(control, quote, role="historical_control"),
                "listed_from": listed_from,
                "listed_to": listed_to,
                "signal_eligible": False,
            }
            for quote in rows
        )
        source_counts.update(quote.source_interface for quote in rows)
        historical_control_coverage.append(
            {
                "security_id": security_id,
                "listed_from": listed_from,
                "listed_to": listed_to,
                "first_observation": rows[0].trading_date,
                "last_observation": rows[-1].trading_date,
                "row_count": len(rows),
                "signal_eligible": False,
            }
        )
    historical_control_rows.sort(
        key=lambda row: (str(row["trading_date"]), str(row["security_id"]))
    )

    for industry, benchmark in selected_benchmarks.items():
        rows = call_market_source(
            f"akshare.benchmark.{benchmark.security_id}",
            partial(primary.benchmark_quotes, benchmark, start=start, end=end),
            max_attempts=max_attempts,
            wait_seconds=retry_delay_seconds,
            secrets=secrets,
            events=retry_events,
        )
        _validate_quotes(benchmark, rows)
        benchmarks[industry] = rows

    benchmark_by_day = {
        industry: {item.trading_date: item.adjusted_close for item in rows}
        for industry, rows in benchmarks.items()
    }
    bars: list[dict[str, object]] = []
    raw_rows: list[dict[str, object]] = []
    for company in companies:
        currency = "HKD" if company.is_hk else "CNY"
        for quote in equity[company.security_id]:
            benchmark_close = benchmark_by_day[company.industry].get(quote.trading_date)
            if benchmark_close is None:
                continue
            extra = supplements.get(company.security_id, {}).get(
                quote.trading_date, PointInTimeSupplement()
            )
            bars.append(
                {
                    "trading_date": quote.trading_date,
                    "security_id": company.security_id,
                    "industry": company.industry,
                    "market": company.market,
                    "currency": currency,
                    "benchmark_id": selected_benchmarks[company.industry].security_id,
                    "benchmark_close": benchmark_close,
                    "adjusted_close": quote.adjusted_close,
                    "volume_shares": quote.volume_shares,
                    "traded_notional": quote.traded_notional,
                    "market_cap": extra.market_cap,
                    "tradable": extra.tradable,
                    "limit_up": extra.limit_up,
                    "limit_down": extra.limit_down,
                    "price_limit_status_source": (
                        "tushare.stk_limit"
                        if extra.price_limit_observed
                        else (
                            "sse.exchange_rule_derived"
                            if extra.price_limit_derived
                            else "missing"
                        )
                    ),
                    "source_interface": quote.source_interface,
                }
            )
            raw_rows.append(_raw_row(company, quote, role="security"))
            source_counts[quote.source_interface] += 1
    for industry, rows in benchmarks.items():
        benchmark = selected_benchmarks[industry]
        for quote in rows:
            raw_rows.append(_raw_row(benchmark, quote, role="benchmark"))
            source_counts[quote.source_interface] += 1
    bars.sort(key=lambda row: (str(row["trading_date"]), str(row["security_id"])))
    raw_rows.sort(key=lambda row: (str(row["trading_date"]), str(row["security_id"])))
    if not bars:
        raise MarketSourceError("研究证券与事前基准没有可冻结的行情交集")

    coverage_start = cast(date, bars[0]["trading_date"])
    coverage_end = cast(date, bars[-1]["trading_date"])
    benchmark_day_sets = [
        {item.trading_date.isoformat() for item in rows} for rows in benchmarks.values()
    ]
    a_days = set().union(*benchmark_day_sets)
    if any(days != a_days for days in benchmark_day_sets):
        raise MarketSourceError("事前绑定的 A 股基准交易日历不一致")
    hk_days = {
        item.trading_date.isoformat()
        for company in companies
        if company.is_hk
        for item in equity[company.security_id]
    }
    trade_cal_permission_verified = "trade_cal" in tushare_endpoints
    # 120 积分账号的 trade_cal 实测频控为每小时一次。行情构建不得消耗这条低频配额；
    # 当前只冻结单日权限探测事实，完整日历仍以 AKShare 指数观测生成。
    tushare_calendar_days = {item.isoformat() for item in trading_calendar_cache.open_days}
    calendar_session_days = {item.isoformat() for item in trading_calendar_cache.session_days}
    comparable_akshare_days = a_days & calendar_session_days
    calendar_overlap = comparable_akshare_days & tushare_calendar_days
    calendar_passed = bool(calendar_session_days) and (
        comparable_akshare_days == tushare_calendar_days
    )
    calendar_quality = {
        "status": (
            "passed"
            if calendar_passed
            else (
                "mismatch"
                if calendar_session_days
                else (
                    "permission_probe_only_rate_limited"
                    if trade_cal_permission_verified
                    else "not_available"
                )
            )
        ),
        "permission_verified": trade_cal_permission_verified,
        "cached_crosscheck_enabled": bool(calendar_session_days),
        "comparison_start": min(calendar_session_days) if calendar_session_days else None,
        "comparison_end": max(calendar_session_days) if calendar_session_days else None,
        "akshare_observed_open_days": len(comparable_akshare_days),
        "tushare_open_days": len(tushare_calendar_days),
        "overlap_open_days": len(calendar_overlap),
        "akshare_only_days": sorted(comparable_akshare_days - tushare_calendar_days),
        "tushare_only_days": sorted(tushare_calendar_days - comparable_akshare_days),
        "passed": calendar_passed,
    }
    cross_source_passed = bool(quality_by_security) and all(
        bool(item["passed"]) for item in quality_by_security
    )
    if supplement is not None and "daily" in tushare_endpoints and not cross_source_passed:
        raise MarketSourceError("AKShare 与 Tushare 日线跨源质量门禁未通过，拒绝冻结")
    all_market_caps = all(row["market_cap"] is not None for row in bars)
    a_rows = [row for row in bars if row["market"] == "A股"]
    all_a_market_caps = bool(a_rows) and all(row["market_cap"] is not None for row in a_rows)
    all_a_limit_status = bool(a_rows) and all(
        (
            observed_status := supplements.get(str(row["security_id"]), {}).get(
                cast(date, row["trading_date"])
            )
        )
        is not None
        and (observed_status.price_limit_observed or observed_status.price_limit_derived)
        for row in a_rows
    )
    all_a_limit_status_observed = bool(a_rows) and all(
        (
            observed_status := supplements.get(str(row["security_id"]), {}).get(
                cast(date, row["trading_date"])
            )
        )
        is not None
        and observed_status.price_limit_observed
        for row in a_rows
    )

    corporate_action_rows: list[dict[str, object]] = []
    if fetch_structured_actions:
        if any(company.is_hk for company in companies):
            raise MarketSourceError("结构化公司行动硬门禁当前只支持纯 A 股研究池")
        for company in companies:
            actions = call_market_source(
                f"akshare.corporate_actions.{company.security_id}",
                partial(
                    primary.a_share_corporate_actions,
                    company,
                    start=start,
                    end=end,
                ),
                max_attempts=max_attempts,
                wait_seconds=retry_delay_seconds,
                secrets=secrets,
                events=retry_events,
            )
            for action in actions:
                identity = (
                    f"{action.security_id}:{action.ex_date}:{action.action_type}:"
                    f"{action.ratio}:{action.cash_amount}"
                )
                corporate_action_rows.append(
                    {
                        "action_id": f"CA-{sha256(identity.encode()).hexdigest()[:20]}",
                        "security_id": action.security_id,
                        "announced_at": action.announced_at,
                        "ex_date": action.ex_date,
                        "action_type": action.action_type,
                        "ratio": action.ratio,
                        "cash_amount": action.cash_amount,
                        "currency": action.currency,
                        "source_locator": action.source_locator,
                    }
                )
        corporate_action_rows.sort(
            key=lambda item: (str(item["ex_date"]), str(item["security_id"]))
        )

    bars_hash = _write(
        destination / "bars.json",
        {"schema_version": "portfolio-bars-v1", "data_version": version, "rows": bars},
    )
    calendar_markets = {
        "A股": _calendar(
            a_days,
            coverage_start,
            coverage_end,
            source="akshare.index_observation",
        )
    }
    if hk_days:
        calendar_markets["港股"] = _calendar(
            hk_days,
            coverage_start,
            coverage_end,
            source="akshare.hk_equity_observation",
        )
    calendar_hash = _write(
        destination / "calendar.json",
        {
            "schema_version": "trading-calendar-v1",
            "data_version": f"{version}-calendar",
            "markets": calendar_markets,
        },
    )
    action_hash = _write(
        destination / "corporate_actions.json",
        {
            "schema_version": "corporate-action-ledger-v1",
            "data_version": f"{version}-corporate-actions",
            "adjustment_contract": "AKShare 前复权序列已反映除权除息；独立事件只审计，不重复调整",
            "coverage_status": (
                "structured_dividend_and_share_distribution_complete"
                if fetch_structured_actions
                else "adjustment_embedded; structured_event_feed_not_enabled"
            ),
            "events": corporate_action_rows,
        },
    )
    historical_control_hash = (
        _write(
            destination / "historical_controls.json",
            {
                "schema_version": "historical-delisted-control-v1",
                "data_version": f"{version}-historical-controls",
                "purpose": "退市与幸存者偏差影子对照；不进入当前信号池或 Alpha 宣称",
                "coverage": historical_control_coverage,
                "rows": historical_control_rows,
            },
        )
        if historical_controls
        else None
    )
    governance_hashes = {
        key: _write(destination / f"{key}.json", payload)
        for key, payload in sorted((governance_assets or {}).items())
    }
    raw_hash = _write(
        destination / "source_snapshot.json",
        {
            "schema_version": "market-source-snapshot-v1",
            "data_version": version,
            "adjustment": "qfq",
            "adjustment_anchor_date": end,
            "rows": raw_rows,
        },
    )
    cross_snapshot_hash = _write(
        destination / "cross_source_snapshot.json",
        {
            "schema_version": "market-cross-source-snapshot-v1",
            "data_version": version,
            "scope": "A股未复权日线；仅用于来源对账，不进入回测价格序列",
            "rows": cross_source_snapshot,
        },
    )
    quality_hash = _write(
        destination / "cross_source_quality.json",
        {
            "schema_version": "market-cross-source-quality-v1",
            "data_version": version,
            "status": "passed" if cross_source_passed else "not_enabled",
            "thresholds": QUALITY_THRESHOLDS,
            "securities": quality_by_security,
            "trading_calendar": calendar_quality,
        },
    )
    permission_hash = _write(
        destination / "tushare_permission_profile.json",
        permission_profile
        or {
            "schema_version": "tushare-permission-probe-v1",
            "status": "not_configured",
            "credential_persisted": False,
            "endpoints": [],
        },
    )
    price_limit_snapshot_rows: list[dict[str, object]] = [
        {
            "security_id": security_id,
            "trading_date": trading_date,
            "limit_up": observation.limit_up,
            "limit_down": observation.limit_down,
            "price_limit_observed": True,
            "price_limit_derived": False,
            "status_source": "tushare.stk_limit",
        }
        for security_id, observations in sorted(price_limit_cache.by_security.items())
        for trading_date, observation in sorted(observations.items())
    ]
    if price_limit_derivation_set is not None:
        price_limit_snapshot_rows.extend(
            {
                "security_id": item.security_id,
                "trading_date": item.trading_date,
                "pre_close": item.pre_close,
                "close": item.close,
                "limit_rate": item.limit_rate,
                "upper_limit": item.upper_limit,
                "lower_limit": item.lower_limit,
                "limit_up": item.limit_up,
                "limit_down": item.limit_down,
                "price_limit_observed": False,
                "price_limit_derived": True,
                "status_source": "sse.exchange_rule_derived",
                "derivation_set_id": price_limit_derivation_set.derivation_set_id,
                "rule_id": price_limit_derivation_set.rule_id,
                "rule_source_url": price_limit_derivation_set.source_url,
            }
            for item in price_limit_derivation_set.rows
        )
    price_limit_snapshot_rows.sort(
        key=lambda row: (str(row["security_id"]), str(row["trading_date"]))
    )
    reference_snapshot_hash = _write(
        destination / "tushare_reference_snapshot.json",
        {
            "schema_version": (
                "tushare-reference-snapshot-v2"
                if price_limit_derivation_set is not None
                else "tushare-reference-snapshot-v1"
            ),
            "data_version": version,
            "market_cap": {
                "source": "tushare.daily_basic",
                "source_files": market_cap_cache.files,
                "rows": [
                    {
                        "security_id": security_id,
                        "trading_date": trading_date,
                        "total_market_cap": market_cap,
                    }
                    for security_id, observations in sorted(market_cap_cache.by_security.items())
                    for trading_date, market_cap in sorted(observations.items())
                ],
            },
            "trade_calendar": {
                "source": "tushare.trade_cal",
                "source_files": trading_calendar_cache.files,
                "session_days": sorted(trading_calendar_cache.session_days),
                "open_days": sorted(trading_calendar_cache.open_days),
            },
            "price_limits": {
                "source": (
                    "tushare.daily+tushare.stk_limit+sse.exchange_rule_derived"
                    if price_limit_derivation_set is not None
                    else "tushare.daily+tushare.stk_limit"
                ),
                "source_files": price_limit_cache.files,
                "observed_row_count": price_limit_cache.row_count,
                "derived_row_count": derived_price_limit_count,
                "rows": price_limit_snapshot_rows,
            },
        },
    )
    reference_source_files = []
    if reference_cache_root is not None:
        for relative in sorted(
            set(market_cap_cache.files)
            | set(trading_calendar_cache.files)
            | set(price_limit_cache.files)
        ):
            path = reference_cache_root / relative
            reference_source_files.append(
                {"path": relative, "sha256": sha256(path.read_bytes()).hexdigest()}
            )
    provenance_hash = _write(
        destination / "provenance.json",
        {
            "schema_version": "market-provenance-v1",
            "data_version": version,
            "primary": {
                "source_id": primary.source_id,
                "library": "akshare",
                "library_version": primary.library_version,
                "interfaces": [
                    "stock_zh_a_hist_tx",
                    *(["stock_hk_daily"] if hk_days else []),
                    "stock_zh_index_daily_tx",
                    *(["stock_history_dividend_detail"] if fetch_structured_actions else []),
                ],
                "upstream_providers": ["Tencent Finance", "Sina Finance"],
            },
            "supplement": {
                "source_id": supplement.source_id if supplement else "tushare-not-configured",
                "configured": supplement is not None,
                "library_version": supplement.library_version if supplement else None,
                "api_origin": supplement.api_origin if supplement else None,
                "fallback_security_count": fallback_count,
                "fallback_reasons": fallback_reasons,
                "available_endpoints": sorted(tushare_endpoints),
                "errors": supplement_errors,
            },
            "request": {"start": start, "end": end, "adjustment": "qfq"},
            "retry_policy": {
                "max_attempts": max_attempts,
                "delay_seconds": retry_delay_seconds,
                "events": [event.to_dict() for event in retry_events],
            },
            "reference_cache": {
                "configured": reference_cache_root is not None,
                "market_cap_rows": market_cap_cache.row_count,
                "price_limit_observed_rows": price_limit_cache.row_count,
                "price_limit_derived_rows": derived_price_limit_count,
                "price_limit_effective_rows": (
                    price_limit_cache.row_count + derived_price_limit_count
                ),
                "source_files": reference_source_files,
            },
            "row_source_counts": dict(sorted(source_counts.items())),
        },
    )
    limitations = [
        "AKShare 是研究型聚合接口；上游网页或字段变化时构建必须失败并人工复核，禁止静默切源",
        "前复权值随锚点可能变化；本版本已固定抓取截止日和源快照，后续只能新增版本",
    ]
    if fetch_structured_actions:
        limitations.append("结构化公司行动当前覆盖分红送转；仍需独立来源复核合并、拆股等其他事件")
    else:
        limitations.append(
            "结构化公司行动事件源未启用；前复权效果可使用，不能声称完成逐事件复权审计"
        )
    if historical_controls:
        limitations.append(
            "退市证券仅作为生存者偏差影子对照，不具备点时行业、基准或人工信号时不得进入收益评价"
        )
    if hk_days:
        limitations.append(
            "港股为 HKD、行业基准为 CNY；未冻结 FX 时不得把混币种超额收益解释为 Alpha"
        )
    if not all_market_caps:
        limitations.append(
            "全市场点时市值未覆盖港股；包含港股的组合继续关闭市值中性"
            if all_a_market_caps and hk_days
            else "点时市值未全量覆盖；市值中性开关保持硬门禁关闭"
        )
    if all_a_market_caps:
        limitations.append(
            "A 股点时市值已与冻结行情全量对齐；市值中性仅可用于所选区间无缺口的纯 A 股组合"
        )
    elif market_cap_cache.row_count:
        limitations.append(
            f"Tushare daily_basic 低频缓存当前仅覆盖 {market_cap_cache.row_count} 条证券日；"
            "覆盖完整前不得开启点时市值能力"
        )
    if not all_a_limit_status:
        limitations.append("A 股涨跌停状态未全量覆盖；不得声称完成涨跌停可成交性模拟")
    if derived_price_limit_count:
        limitations.append(
            f"涨跌停状态中 {derived_price_limit_count} 条为交易所规则确定性推导，"
            "已保留前收盘、规则、比例、价格和来源谱系；不得冒充 Tushare 直接观测"
        )
        limitations.append(
            "当前涨跌停状态只支持收盘是否封板的日频模拟；"
            "未引入分钟或逐笔行情前，不得声称完成盘中可成交性模拟"
        )
    if price_limit_cache.row_count and not all_a_limit_status:
        limitations.append(
            f"Tushare 涨跌停历史缓存已提供 {price_limit_cache.row_count} 条证券日；"
            "只有与冻结行情全量对齐时能力才会开启"
        )
    if supplement is None:
        limitations.append("未配置 Tushare Token；付费补充字段缺失不影响 AKShare 主链路冻结")
    elif "stk_limit" not in tushare_endpoints:
        limitations.append("Tushare stk_limit 实测无权限；A 股涨跌停状态硬门禁保持关闭")
    if trade_cal_permission_verified and not tushare_calendar_days:
        limitations.append(
            "Tushare trade_cal 已验证单日权限但受每小时一次频控；完整日历双源门禁暂未启用"
        )
    if tushare_calendar_days and not calendar_quality["passed"]:
        limitations.append("AKShare 指数观测交易日与 Tushare 日历存在差异，详见跨源质量报告")

    manifest = {
        "schema_version": "frozen-market-dataset-v1",
        "dataset_id": f"MDS-{version}",
        "data_version": version,
        "status": "frozen",
        "frozen_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "adjustment": "前复权",
        "adjustment_anchor_date": end,
        "timezone": "Asia/Shanghai",
        "authorization": {
            "policy_id": "akshare-public-research-v1",
            "status": "公开行情研究使用已核验",
            "scope": "项目内部研究、复算与审计；禁止对外再分发或用于实盘交易",
            "supplement": {
                "source_id": (supplement.source_id if supplement else "tushare-not-configured"),
                "api_origin": supplement.api_origin if supplement else None,
                "credential_status": ("用户提供有效访问凭证" if supplement else "未配置"),
                "scope": "仅限项目内部研究、交叉核验和字段补充；禁止对外再分发",
            },
        },
        "source_priority": [
            "akshare",
            "tushare_optional",
            *(["sse_exchange_rule_derived"] if derived_price_limit_count else []),
        ],
        "coverage": {"start": coverage_start, "end": coverage_end},
        "securities": [company.security_id for company in companies],
        "assets": {
            "bars": {"path": "bars.json", "sha256": bars_hash},
            "calendar": {"path": "calendar.json", "sha256": calendar_hash},
            "corporate_actions": {
                "path": "corporate_actions.json",
                "sha256": action_hash,
            },
            **(
                {
                    "historical_controls": {
                        "path": "historical_controls.json",
                        "sha256": historical_control_hash,
                    }
                }
                if historical_control_hash is not None
                else {}
            ),
            "source_snapshot": {"path": "source_snapshot.json", "sha256": raw_hash},
            "cross_source_snapshot": {
                "path": "cross_source_snapshot.json",
                "sha256": cross_snapshot_hash,
            },
            "cross_source_quality": {
                "path": "cross_source_quality.json",
                "sha256": quality_hash,
            },
            "tushare_permission_profile": {
                "path": "tushare_permission_profile.json",
                "sha256": permission_hash,
            },
            "tushare_reference_snapshot": {
                "path": "tushare_reference_snapshot.json",
                "sha256": reference_snapshot_hash,
            },
            "provenance": {"path": "provenance.json", "sha256": provenance_hash},
            **{
                key: {"path": f"{key}.json", "sha256": digest}
                for key, digest in governance_hashes.items()
            },
        },
        "capabilities": {
            "adjusted_close": True,
            "trading_calendar": True,
            "suspension_by_missing_session": True,
            "daily_traded_notional": all(row["traded_notional"] is not None for row in bars),
            "capacity_constraint": all(row["traded_notional"] is not None for row in bars),
            "point_in_time_market_cap": all_market_caps,
            "a_share_point_in_time_market_cap": all_a_market_caps,
            "price_limit_status": all_a_limit_status,
            "price_limit_status_fully_observed": all_a_limit_status_observed,
            "price_limit_status_rule_derived": derived_price_limit_count > 0,
            "structured_corporate_action_events": fetch_structured_actions,
            "historical_universe_and_delisted_samples": bool(historical_controls),
            "tushare_supplement_configured": supplement is not None,
            "tushare_daily_crosscheck": cross_source_passed,
            "tushare_trade_calendar_crosscheck": calendar_passed,
            "tushare_trade_calendar_permission_verified": trade_cal_permission_verified,
            "tushare_pro_bar_fallback_authorized": "pro_bar" in tushare_endpoints,
            "tushare_market_cap_cache_consumed": market_cap_cache.row_count > 0,
            "tushare_price_limit_cache_consumed": price_limit_cache.row_count > 0,
        },
        "limitations": limitations,
    }
    _write(destination / "manifest.json", manifest)
    print(
        f"冻结 AKShare 行情 {len(bars)} 行，覆盖 {coverage_start}~{coverage_end}，"
        f"Tushare={'enabled' if supplement else 'disabled'} → {destination}"
    )
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2023-12-01")
    parser.add_argument("--end", default="2026-08-29")
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument(
        "--tushare-token-env",
        default="TUSHARE_TOKEN",
        help="只读取指定环境变量；Token 不写入命令行、日志或冻结资产",
    )
    parser.add_argument(
        "--tushare-token-file",
        type=Path,
        help="读取本地密钥文件；文件路径和 Token 都不会写入冻结资产",
    )
    parser.add_argument("--tushare-api-url-env", default="TUSHARE_API_URL")
    parser.add_argument(
        "--tushare-permission-report",
        type=Path,
        default=DEFAULT_PERMISSION_REPORT,
        help="由 probe_tushare_permissions 生成的脱敏权限报告",
    )
    parser.add_argument(
        "--reference-cache-root",
        type=Path,
        default=DEFAULT_REFERENCE_CACHE_ROOT,
        help="由低频任务生成并经 SHA-256 状态清单验证的 Tushare 参考缓存",
    )
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--retry-delay-seconds", type=float, default=1.0)
    args = parser.parse_args()
    credentials = (
        read_tushare_credentials_file(args.tushare_token_file) if args.tushare_token_file else None
    )
    token = credentials.token if credentials else os.getenv(args.tushare_token_env)
    api_url = (
        credentials.api_url
        if credentials
        else validate_tushare_api_url(os.getenv(args.tushare_api_url_env))
    )
    endpoints: frozenset[str] = frozenset()
    permission_profile: dict[str, object] | None = None
    if token:
        if args.tushare_permission_report.is_file():
            endpoints, permission_profile = load_tushare_permission_profile(
                args.tushare_permission_report
            )
        else:
            endpoints = frozenset({"daily"})
    run(
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
        version=args.version,
        tushare_token=token,
        tushare_api_url=api_url,
        tushare_endpoints=endpoints,
        permission_profile=permission_profile,
        reference_cache_root=args.reference_cache_root,
        max_attempts=args.max_attempts,
        retry_delay_seconds=args.retry_delay_seconds,
    )


if __name__ == "__main__":
    main()
