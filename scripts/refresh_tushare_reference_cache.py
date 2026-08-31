"""低频刷新 Tushare 点时市值与交易日历缓存，不改变产品能力开关。"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, date, datetime, timedelta
from functools import partial
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

from analytics.pipelines.universe import COMPANIES
from app.core.config import PROJECT_ROOT, settings
from app.ingest.market_source_retry import MarketRetryEvent, call_market_source
from app.ingest.market_source_secrets import (
    read_tushare_credentials_file,
    sanitize_secret_text,
    validate_tushare_api_url,
)
from app.ingest.market_sources import MarketSourceError, TushareSupplementSource
from app.services.market_data import FrozenJsonMarketData
from scripts.build_akshare_quant_market_assets import load_tushare_permission_profile

DEFAULT_ROOT = PROJECT_ROOT / ".runtime" / "quant-reference-cache"
DEFAULT_PERMISSION_PROFILE = (
    PROJECT_ROOT
    / "real_data"
    / "quant"
    / "akshare-qfq-tushare120-20260830-v1"
    / "tushare_permission_profile.json"
)


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _atomic_write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_immutable(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
    except FileExistsError as exc:
        raise MarketSourceError(f"参考缓存文件已存在，禁止覆盖: {path.name}") from exc


def _load_state(root: Path) -> dict[str, object]:
    path = root / "state.json"
    if not path.is_file():
        return {
            "schema_version": "tushare-reference-cache-state-v1",
            "files": {},
            "endpoints": {},
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "tushare-reference-cache-state-v1":
        raise MarketSourceError("Tushare 参考缓存状态版本不受支持")
    if not isinstance(payload.get("files"), dict) or not isinstance(payload.get("endpoints"), dict):
        raise MarketSourceError("Tushare 参考缓存状态结构无效")
    return payload


def _bind_source(state: dict[str, object], *, api_origin: str) -> None:
    source = state.get("source")
    files = state.get("files")
    if source is None:
        if isinstance(files, dict) and files:
            raise MarketSourceError(
                "既有参考缓存缺少 API Origin 身份；更换供应端点时必须使用新的缓存目录"
            )
        state["source"] = {"api_origin": api_origin}
        return
    if not isinstance(source, dict) or source.get("api_origin") != api_origin:
        raise MarketSourceError("参考缓存 API Origin 与当前凭证配置不一致")


def endpoint_can_attempt(
    last_attempt_at: str | None, *, now: datetime, minimum_interval_seconds: int
) -> bool:
    if not last_attempt_at:
        return True
    previous = datetime.fromisoformat(last_attempt_at)
    if previous.tzinfo is None:
        raise MarketSourceError("缓存 last_attempt_at 缺少时区")
    return now.astimezone(UTC) - previous.astimezone(UTC) >= timedelta(
        seconds=minimum_interval_seconds
    )


def _registered_file(root: Path, state: dict[str, object], relative: str) -> Path | None:
    files = state["files"]
    assert isinstance(files, dict)
    metadata = files.get(relative)
    if not isinstance(metadata, dict):
        return None
    path = root / relative
    if not path.is_file() or _digest(path) != metadata.get("sha256"):
        raise MarketSourceError(f"Tushare 参考缓存哈希漂移: {relative}")
    return path


def _register_file(
    root: Path,
    state: dict[str, object],
    path: Path,
    *,
    endpoint: str,
    observed_date: date,
    status: str,
    fetched_at: datetime,
) -> str:
    relative = path.relative_to(root).as_posix()
    files = state["files"]
    assert isinstance(files, dict)
    files[relative] = {
        "endpoint": endpoint,
        "observed_date": observed_date,
        "status": status,
        "fetched_at": fetched_at,
        "sha256": _digest(path),
        "bytes": path.stat().st_size,
    }
    return relative


def _record_attempt(
    root: Path,
    state: dict[str, object],
    *,
    endpoint: str,
    attempted_at: datetime,
    target: str,
) -> None:
    endpoints = state["endpoints"]
    assert isinstance(endpoints, dict)
    current = endpoints.setdefault(endpoint, {})
    if not isinstance(current, dict):
        raise MarketSourceError(f"缓存端点状态无效: {endpoint}")
    current["last_attempt_at"] = attempted_at.isoformat()
    current["last_target"] = target
    _atomic_write(root / "state.json", state)


def _latest_trade_calendar_file(
    root: Path,
    state: dict[str, object],
    *,
    year: int,
    now: datetime,
    ttl_days: int,
) -> tuple[Path, dict[str, object]] | None:
    files = state["files"]
    assert isinstance(files, dict)
    candidates = []
    for relative, metadata in files.items():
        if not isinstance(metadata, dict) or metadata.get("endpoint") != "trade_cal":
            continue
        if int(str(metadata.get("observed_date"))[:4]) != year:
            continue
        fetched_at = datetime.fromisoformat(str(metadata.get("fetched_at")))
        if now.astimezone(UTC) - fetched_at.astimezone(UTC) > timedelta(days=ttl_days):
            continue
        path = _registered_file(root, state, str(relative))
        if path is not None:
            candidates.append((fetched_at, path, metadata))
    if not candidates:
        return None
    _, path, metadata = max(candidates, key=lambda item: item[0])
    return path, metadata


def run(
    *,
    current_manifest: Path,
    cache_root: Path = DEFAULT_ROOT,
    token_file: Path | None = None,
    token_env: str = "TUSHARE_TOKEN",
    api_url_env: str = "TUSHARE_API_URL",
    permission_profile_path: Path = DEFAULT_PERMISSION_PROFILE,
    target_date: date | None = None,
    now: datetime | None = None,
    trade_cal_ttl_days: int = 7,
    trade_cal_minimum_interval_seconds: int = 3600,
    max_attempts: int = 3,
    retry_delay_seconds: float = 1.0,
) -> dict[str, object]:
    current_time = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    run_id = f"QRC-{sha256(current_time.isoformat().encode()).hexdigest()[:20]}"
    token: str | None = None
    retry_events: list[MarketRetryEvent] = []
    report: dict[str, object] = {
        "schema_version": "tushare-reference-cache-report-v1",
        "run_id": run_id,
        "started_at": current_time,
        "status": "running",
        "alert": {"severity": "none", "reason": None},
        "capability_switches_changed": False,
    }
    try:
        adapter = FrozenJsonMarketData(current_manifest)
        info = adapter.info()
        recent_days = adapter.trading_days(
            "A股",
            start=max(info.coverage_start, info.coverage_end - timedelta(days=14)),
            end=info.coverage_end,
        )
        if not recent_days:
            raise MarketSourceError("当前冻结版本没有可用的 A 股交易日")
        target_date = target_date or max(recent_days)
        if target_date < max(recent_days):
            raise MarketSourceError("参考缓存目标日不能早于当前冻结版本最新 A 股交易日")
        if target_date > current_time.date():
            raise MarketSourceError("参考缓存目标日不能晚于任务运行日期")
        report["target_date"] = target_date
        credentials = read_tushare_credentials_file(token_file) if token_file else None
        token = credentials.token if credentials else os.getenv(token_env)
        api_url = (
            credentials.api_url if credentials else validate_tushare_api_url(os.getenv(api_url_env))
        )
        if not token:
            raise MarketSourceError("没有配置 Tushare Token")
        available, permission_profile = load_tushare_permission_profile(permission_profile_path)
        source = call_market_source(
            "tushare.initialize",
            lambda: TushareSupplementSource(token, api_url=api_url),
            max_attempts=max_attempts,
            wait_seconds=retry_delay_seconds,
            secrets=(token,),
            events=retry_events,
        )
        state = _load_state(cache_root)
        _bind_source(state, api_origin=source.api_origin)
        _atomic_write(cache_root / "state.json", state)
        endpoint_state = state["endpoints"]
        assert isinstance(endpoint_state, dict)

        daily_relative = f"daily_basic/{target_date.isoformat()}.json"
        daily_path = _registered_file(cache_root, state, daily_relative)
        if daily_path is not None:
            daily_payload = json.loads(daily_path.read_text(encoding="utf-8"))
            daily_result = {
                "status": "reused",
                "path": daily_relative,
                "trading_date": target_date,
                "coverage": daily_payload.get("coverage"),
            }
        elif "daily_basic" not in available:
            daily_result = {
                "status": "permission_unavailable",
                "trading_date": target_date,
            }
        else:
            daily_state = endpoint_state.get("daily_basic")
            last_target = (
                str(daily_state.get("last_target"))
                if isinstance(daily_state, dict) and daily_state.get("last_target")
                else None
            )
            if last_target == target_date.isoformat():
                daily_result = {
                    "status": "throttled",
                    "trading_date": target_date,
                    "reason": "该目标交易日已经尝试过，禁止重复消耗 daily_basic 配额",
                }
            else:
                _record_attempt(
                    cache_root,
                    state,
                    endpoint="daily_basic",
                    attempted_at=current_time,
                    target=target_date.isoformat(),
                )
                try:
                    # 低频配额接口失败时不自动重试；下一目标交易日再尝试。
                    snapshot = call_market_source(
                        f"tushare.daily_basic.{target_date}",
                        lambda: source.daily_basic_snapshot(COMPANIES, trading_date=target_date),
                        max_attempts=1,
                        wait_seconds=retry_delay_seconds,
                        secrets=(token,),
                        events=retry_events,
                    )
                    cache_status = "complete" if not snapshot.missing_security_ids else "partial"
                    daily_path = cache_root / daily_relative
                    _write_immutable(
                        daily_path,
                        {
                            "schema_version": "tushare-daily-basic-cache-v1",
                            "status": cache_status,
                            "trading_date": target_date,
                            "fetched_at": current_time,
                            "source": "tushare.daily_basic",
                            "sdk_version": source.library_version,
                            "api_origin": source.api_origin,
                            "permission_profile_probed_at": permission_profile.get("probed_at"),
                            "upstream_row_count": snapshot.upstream_row_count,
                            "coverage": {
                                "requested": len([item for item in COMPANIES if not item.is_hk]),
                                "observed": len(snapshot.by_security),
                                "missing_security_ids": snapshot.missing_security_ids,
                            },
                            "rows": [
                                {
                                    "security_id": item.security_id,
                                    "total_market_cap": item.total_market_cap,
                                    "circulating_market_cap": item.circulating_market_cap,
                                }
                                for item in sorted(
                                    snapshot.by_security.values(),
                                    key=lambda value: value.security_id,
                                )
                            ],
                        },
                    )
                    _register_file(
                        cache_root,
                        state,
                        daily_path,
                        endpoint="daily_basic",
                        observed_date=target_date,
                        status=cache_status,
                        fetched_at=current_time,
                    )
                    _atomic_write(cache_root / "state.json", state)
                    daily_result = {
                        "status": cache_status,
                        "path": daily_relative,
                        "trading_date": target_date,
                        "coverage": {
                            "requested": len([item for item in COMPANIES if not item.is_hk]),
                            "observed": len(snapshot.by_security),
                            "missing_security_ids": snapshot.missing_security_ids,
                        },
                    }
                except Exception as exc:
                    daily_result = {
                        "status": "failed",
                        "trading_date": target_date,
                        "reason": sanitize_secret_text(str(exc), secrets=(token,)),
                    }

        cached_calendar = _latest_trade_calendar_file(
            cache_root,
            state,
            year=target_date.year,
            now=current_time,
            ttl_days=trade_cal_ttl_days,
        )
        if cached_calendar is not None:
            calendar_path, metadata = cached_calendar
            calendar_result = {
                "status": "reused",
                "path": calendar_path.relative_to(cache_root).as_posix(),
                "fetched_at": metadata.get("fetched_at"),
            }
        elif "trade_cal" not in available:
            calendar_result = {"status": "permission_unavailable"}
        else:
            trade_state = endpoint_state.get("trade_cal")
            last_attempt = (
                str(trade_state.get("last_attempt_at"))
                if isinstance(trade_state, dict) and trade_state.get("last_attempt_at")
                else None
            )
            if not endpoint_can_attempt(
                last_attempt,
                now=current_time,
                minimum_interval_seconds=trade_cal_minimum_interval_seconds,
            ):
                calendar_result = {
                    "status": "throttled",
                    "last_attempt_at": last_attempt,
                }
            else:
                _record_attempt(
                    cache_root,
                    state,
                    endpoint="trade_cal",
                    attempted_at=current_time,
                    target=str(target_date.year),
                )
                try:
                    sessions = call_market_source(
                        f"tushare.trade_cal.{target_date.year}",
                        lambda: source.a_share_calendar(
                            start=date(target_date.year, 1, 1),
                            end=date(target_date.year, 12, 31),
                        ),
                        max_attempts=1,
                        wait_seconds=retry_delay_seconds,
                        secrets=(token,),
                        events=retry_events,
                    )
                except Exception as exc:
                    calendar_result = {
                        "status": "failed",
                        "reason": sanitize_secret_text(str(exc), secrets=(token,)),
                    }
                    sessions = None
                if sessions is None:
                    pass
                else:
                    tushare_open = {
                        item.calendar_date
                        for item in sessions
                        if item.is_open and item.calendar_date <= info.coverage_end
                    }
                    akshare_open = set(
                        adapter.trading_days(
                            "A股",
                            start=max(info.coverage_start, date(target_date.year, 1, 1)),
                            end=info.coverage_end,
                        )
                    )
                    matched = tushare_open == akshare_open
                    calendar_status = "matched" if matched else "mismatch"
                    timestamp = current_time.strftime("%Y%m%dT%H%M%S")
                    calendar_path = (
                        cache_root / "trade_cal" / f"SSE-{target_date.year}-asof-{timestamp}.json"
                    )
                    _write_immutable(
                        calendar_path,
                        {
                            "schema_version": "tushare-trade-calendar-cache-v1",
                            "status": calendar_status,
                            "exchange": "SSE",
                            "year": target_date.year,
                            "fetched_at": current_time,
                            "source": "tushare.trade_cal",
                            "sdk_version": source.library_version,
                            "api_origin": source.api_origin,
                            "comparison": {
                                "through": info.coverage_end,
                                "akshare_open_days": len(akshare_open),
                                "tushare_open_days": len(tushare_open),
                                "akshare_only": sorted(akshare_open - tushare_open),
                                "tushare_only": sorted(tushare_open - akshare_open),
                            },
                            "sessions": [
                                {
                                    "calendar_date": item.calendar_date,
                                    "is_open": item.is_open,
                                    "previous_trading_date": item.previous_trading_date,
                                }
                                for item in sessions
                            ],
                        },
                    )
                    calendar_relative = _register_file(
                        cache_root,
                        state,
                        calendar_path,
                        endpoint="trade_cal",
                        observed_date=date(target_date.year, 12, 31),
                        status=calendar_status,
                        fetched_at=current_time,
                    )
                    _atomic_write(cache_root / "state.json", state)
                    calendar_result = {
                        "status": calendar_status,
                        "path": calendar_relative,
                        "comparison": {
                            "through": info.coverage_end,
                            "akshare_open_days": len(akshare_open),
                            "tushare_open_days": len(tushare_open),
                            "akshare_only": sorted(akshare_open - tushare_open),
                            "tushare_only": sorted(tushare_open - akshare_open),
                        },
                    }

        report["daily_basic"] = daily_result
        report["trade_cal"] = calendar_result
        partial_statuses = {
            "partial",
            "mismatch",
            "throttled",
            "permission_unavailable",
            "failed",
        }
        is_partial = (
            str(daily_result.get("status")) in partial_statuses
            or str(calendar_result.get("status")) in partial_statuses
        )
        report["status"] = "partial" if is_partial else "ready"
        if is_partial:
            report["alert"] = {
                "severity": "warning",
                "reason": "参考缓存仍有未覆盖或待复核项目；产品能力开关保持关闭",
            }
        return report
    except Exception as exc:
        report["status"] = "failed"
        report["alert"] = {
            "severity": "critical",
            "reason": sanitize_secret_text(str(exc), secrets=(token,) if token else ()),
        }
        return report
    finally:
        report["retry_events"] = [item.to_dict() for item in retry_events]
        report["finished_at"] = datetime.now(ZoneInfo("Asia/Shanghai"))
        encoded = (
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"
        )
        if token and token in encoded:
            raise RuntimeError("安全门禁失败：参考缓存报告包含 Token")
        cache_root.mkdir(parents=True, exist_ok=True)
        (cache_root / "latest.json").write_text(encoded, encoding="utf-8")
        run_path = cache_root / "runs" / f"{run_id}.json"
        run_path.parent.mkdir(parents=True, exist_ok=True)
        run_path.write_text(encoded, encoding="utf-8")


def backfill_history(
    *,
    current_manifest: Path,
    cache_root: Path,
    token_file: Path | None = None,
    token_env: str = "TUSHARE_TOKEN",
    api_url_env: str = "TUSHARE_API_URL",
    permission_profile_path: Path = DEFAULT_PERMISSION_PROFILE,
    max_attempts: int = 2,
    retry_delay_seconds: float = 1.0,
) -> dict[str, object]:
    """按证券少量区间调用回填市值和涨跌停，写入不可变参考缓存。"""

    started_at = datetime.now(ZoneInfo("Asia/Shanghai"))
    run_id = f"QRH-{sha256(started_at.isoformat().encode()).hexdigest()[:20]}"
    token: str | None = None
    retry_events: list[MarketRetryEvent] = []
    report: dict[str, object] = {
        "schema_version": "tushare-reference-history-report-v1",
        "run_id": run_id,
        "started_at": started_at,
        "status": "running",
        "capability_switches_changed": False,
        "securities": [],
    }
    try:
        adapter = FrozenJsonMarketData(current_manifest)
        info = adapter.info()
        credentials = read_tushare_credentials_file(token_file) if token_file else None
        token = credentials.token if credentials else os.getenv(token_env)
        api_url = (
            credentials.api_url if credentials else validate_tushare_api_url(os.getenv(api_url_env))
        )
        if not token:
            raise MarketSourceError("没有配置 Tushare Token")
        available, permission_profile = load_tushare_permission_profile(permission_profile_path)
        required = {"daily", "daily_basic", "stk_limit"}
        missing_endpoints = sorted(required - available)
        if missing_endpoints:
            raise MarketSourceError(f"历史参考回填缺少实测权限: {', '.join(missing_endpoints)}")
        source = call_market_source(
            "tushare.initialize",
            lambda: TushareSupplementSource(token, api_url=api_url),
            max_attempts=max_attempts,
            wait_seconds=retry_delay_seconds,
            secrets=(token,),
            events=retry_events,
        )
        state = _load_state(cache_root)
        _bind_source(state, api_origin=source.api_origin)
        _atomic_write(cache_root / "state.json", state)
        security_results: list[dict[str, object]] = []
        for company in (item for item in COMPANIES if not item.is_hk):
            relative = (
                f"reference_history/{company.security_id}-"
                f"{info.coverage_start}-{info.coverage_end}.json"
            )
            existing = _registered_file(cache_root, state, relative)
            if existing is not None:
                payload = json.loads(existing.read_text(encoding="utf-8"))
                security_results.append(
                    {
                        "security_id": company.security_id,
                        "status": "reused",
                        "path": relative,
                        "coverage": payload.get("coverage"),
                    }
                )
                continue
            _record_attempt(
                cache_root,
                state,
                endpoint=f"reference_history:{company.security_id}",
                attempted_at=started_at,
                target=f"{info.coverage_start}:{info.coverage_end}",
            )
            try:
                market_caps = call_market_source(
                    f"tushare.daily_basic.history.{company.security_id}",
                    partial(
                        source.daily_basic_history,
                        company,
                        start=info.coverage_start,
                        end=info.coverage_end,
                    ),
                    max_attempts=max_attempts,
                    wait_seconds=retry_delay_seconds,
                    secrets=(token,),
                    events=retry_events,
                )
                price_limits = call_market_source(
                    f"tushare.price_limit.history.{company.security_id}",
                    partial(
                        source.price_limit_history,
                        company,
                        start=info.coverage_start,
                        end=info.coverage_end,
                    ),
                    max_attempts=max_attempts,
                    wait_seconds=retry_delay_seconds,
                    secrets=(token,),
                    events=retry_events,
                )
                expected_days = {
                    item.trading_date
                    for item in adapter.bars(
                        (company.security_id,),
                        start=info.coverage_start,
                        end=info.coverage_end,
                    )
                }
                market_by_day = {item.trading_date: item for item in market_caps}
                limit_by_day = {item.trading_date: item for item in price_limits}
                missing_market_cap = sorted(expected_days - market_by_day.keys())
                missing_price_limit = sorted(expected_days - limit_by_day.keys())
                cache_status = (
                    "complete" if not missing_market_cap and not missing_price_limit else "partial"
                )
                path = cache_root / relative
                _write_immutable(
                    path,
                    {
                        "schema_version": "tushare-reference-history-cache-v1",
                        "status": cache_status,
                        "security_id": company.security_id,
                        "fetched_at": started_at,
                        "api_origin": source.api_origin,
                        "sdk_version": source.library_version,
                        "permission_profile_probed_at": permission_profile.get("probed_at"),
                        "coverage": {
                            "start": info.coverage_start,
                            "end": info.coverage_end,
                            "expected_rows": len(expected_days),
                            "market_cap_rows": len(expected_days & market_by_day.keys()),
                            "price_limit_rows": len(expected_days & limit_by_day.keys()),
                            "missing_market_cap_dates": missing_market_cap,
                            "missing_price_limit_dates": missing_price_limit,
                        },
                        "rows": [
                            {
                                "security_id": company.security_id,
                                "trading_date": trading_date,
                                "total_market_cap": (
                                    market_by_day[trading_date].total_market_cap
                                    if trading_date in market_by_day
                                    else None
                                ),
                                "circulating_market_cap": (
                                    market_by_day[trading_date].circulating_market_cap
                                    if trading_date in market_by_day
                                    else None
                                ),
                                "market_cap_observed": trading_date in market_by_day,
                                "price_limit_observed": trading_date in limit_by_day,
                                "limit_up": (
                                    limit_by_day[trading_date].limit_up
                                    if trading_date in limit_by_day
                                    else False
                                ),
                                "limit_down": (
                                    limit_by_day[trading_date].limit_down
                                    if trading_date in limit_by_day
                                    else False
                                ),
                            }
                            for trading_date in sorted(expected_days)
                        ],
                    },
                )
                _register_file(
                    cache_root,
                    state,
                    path,
                    endpoint="reference_history",
                    observed_date=info.coverage_end,
                    status=cache_status,
                    fetched_at=started_at,
                )
                _atomic_write(cache_root / "state.json", state)
                security_results.append(
                    {
                        "security_id": company.security_id,
                        "status": cache_status,
                        "path": relative,
                        "coverage": {
                            "expected_rows": len(expected_days),
                            "market_cap_rows": len(expected_days & market_by_day.keys()),
                            "price_limit_rows": len(expected_days & limit_by_day.keys()),
                            "missing_market_cap_dates": len(missing_market_cap),
                            "missing_price_limit_dates": len(missing_price_limit),
                        },
                    }
                )
            except Exception as exc:
                security_results.append(
                    {
                        "security_id": company.security_id,
                        "status": "failed",
                        "reason": sanitize_secret_text(str(exc), secrets=(token,)),
                    }
                )
        report["api_origin"] = source.api_origin
        report["coverage"] = {
            "start": info.coverage_start,
            "end": info.coverage_end,
        }
        report["securities"] = security_results
        statuses = {str(item["status"]) for item in security_results}
        report["status"] = (
            "ready"
            if statuses <= {"complete", "reused"}
            else ("failed" if statuses == {"failed"} else "partial")
        )
        return report
    except Exception as exc:
        report["status"] = "failed"
        report["alert"] = {
            "severity": "critical",
            "reason": sanitize_secret_text(str(exc), secrets=(token,) if token else ()),
        }
        return report
    finally:
        report["retry_events"] = [item.to_dict() for item in retry_events]
        report["finished_at"] = datetime.now(ZoneInfo("Asia/Shanghai"))
        encoded = (
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"
        )
        if token and token in encoded:
            raise RuntimeError("安全门禁失败：历史参考缓存报告包含 Token")
        cache_root.mkdir(parents=True, exist_ok=True)
        (cache_root / "history-latest.json").write_text(encoded, encoding="utf-8")
        run_path = cache_root / "history-runs" / f"{run_id}.json"
        run_path.parent.mkdir(parents=True, exist_ok=True)
        run_path.write_text(encoded, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--current-manifest", type=Path, default=settings.quant_default_market_manifest
    )
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--tushare-token-file", type=Path)
    parser.add_argument("--tushare-token-env", default="TUSHARE_TOKEN")
    parser.add_argument("--tushare-api-url-env", default="TUSHARE_API_URL")
    parser.add_argument(
        "--tushare-permission-profile",
        type=Path,
        default=DEFAULT_PERMISSION_PROFILE,
    )
    parser.add_argument("--target-date", type=date.fromisoformat)
    parser.add_argument(
        "--backfill-history",
        action="store_true",
        help="按证券区间回填 daily_basic 与涨跌停状态；只写不可变参考缓存",
    )
    parser.add_argument("--trade-cal-ttl-days", type=int, default=7)
    parser.add_argument("--trade-cal-minimum-interval-seconds", type=int, default=3600)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--retry-delay-seconds", type=float, default=1.0)
    args = parser.parse_args()
    if args.backfill_history:
        result = backfill_history(
            current_manifest=args.current_manifest,
            cache_root=args.cache_root,
            token_file=args.tushare_token_file,
            token_env=args.tushare_token_env,
            api_url_env=args.tushare_api_url_env,
            permission_profile_path=args.tushare_permission_profile,
            max_attempts=args.max_attempts,
            retry_delay_seconds=args.retry_delay_seconds,
        )
    else:
        result = run(
            current_manifest=args.current_manifest,
            cache_root=args.cache_root,
            token_file=args.tushare_token_file,
            token_env=args.tushare_token_env,
            api_url_env=args.tushare_api_url_env,
            permission_profile_path=args.tushare_permission_profile,
            target_date=args.target_date,
            trade_cal_ttl_days=args.trade_cal_ttl_days,
            trade_cal_minimum_interval_seconds=args.trade_cal_minimum_interval_seconds,
            max_attempts=args.max_attempts,
            retry_delay_seconds=args.retry_delay_seconds,
        )
    print(f"Tushare 参考缓存刷新 {result['status']} → {args.cache_root}")
    if result["status"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
