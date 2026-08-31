"""读取并验证本地 Tushare 低频参考数据缓存。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from app.ingest.market_sources import MarketSourceError, PriceLimitObservation


@dataclass(frozen=True)
class MarketCapCacheLoad:
    by_security: dict[str, dict[date, Decimal]]
    files: tuple[str, ...]
    row_count: int


@dataclass(frozen=True)
class TradingCalendarCacheLoad:
    open_days: frozenset[date]
    session_days: frozenset[date]
    files: tuple[str, ...]


@dataclass(frozen=True)
class PriceLimitCacheLoad:
    by_security: dict[str, dict[date, PriceLimitObservation]]
    files: tuple[str, ...]
    row_count: int


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def load_market_cap_cache(root: Path, *, start: date, end: date) -> MarketCapCacheLoad:
    state_path = root / "state.json"
    if not state_path.is_file():
        return MarketCapCacheLoad({}, (), 0)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("schema_version") != "tushare-reference-cache-state-v1":
        raise MarketSourceError("Tushare 参考缓存状态版本不受支持")
    files = state.get("files")
    if not isinstance(files, dict):
        raise MarketSourceError("Tushare 参考缓存状态缺少 files")

    result: dict[str, dict[date, Decimal]] = {}
    loaded_files: list[str] = []
    row_count = 0
    for relative, metadata in sorted(files.items()):
        if not isinstance(metadata, dict) or metadata.get("endpoint") not in {
            "daily_basic",
            "reference_history",
        }:
            continue
        path = (root / str(relative)).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as exc:
            raise MarketSourceError("Tushare 参考缓存路径越界") from exc
        if not path.is_file() or _digest(path) != metadata.get("sha256"):
            raise MarketSourceError(f"Tushare 参考缓存哈希漂移: {relative}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("rows")
        if not isinstance(rows, list):
            raise MarketSourceError(f"daily_basic 缓存 rows 无效: {relative}")
        schema_version = payload.get("schema_version")
        if schema_version not in {
            "tushare-daily-basic-cache-v1",
            "tushare-reference-history-cache-v1",
        }:
            raise MarketSourceError(f"daily_basic 缓存版本不受支持: {relative}")
        for row in rows:
            if not isinstance(row, dict):
                raise MarketSourceError(f"daily_basic 缓存行无效: {relative}")
            observed = date.fromisoformat(
                str(row.get("trading_date") or payload.get("trading_date"))
            )
            if observed < start or observed > end:
                continue
            security_id = str(row.get("security_id") or "")
            raw_market_cap = row.get("total_market_cap")
            if raw_market_cap is None:
                continue
            market_cap = Decimal(str(raw_market_cap))
            if not security_id or market_cap <= 0:
                raise MarketSourceError(f"daily_basic 缓存证券或市值无效: {relative}")
            security_rows = result.setdefault(security_id, {})
            if observed in security_rows and security_rows[observed] != market_cap:
                raise MarketSourceError(
                    f"daily_basic 缓存同证券同日存在冲突: {security_id} {observed}"
                )
            security_rows[observed] = market_cap
            row_count += 1
        loaded_files.append(str(relative))
    row_count = sum(len(observations) for observations in result.values())
    return MarketCapCacheLoad(result, tuple(loaded_files), row_count)


def load_price_limit_cache(root: Path, *, start: date, end: date) -> PriceLimitCacheLoad:
    state_path = root / "state.json"
    if not state_path.is_file():
        return PriceLimitCacheLoad({}, (), 0)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("schema_version") != "tushare-reference-cache-state-v1":
        raise MarketSourceError("Tushare 参考缓存状态版本不受支持")
    files = state.get("files")
    if not isinstance(files, dict):
        raise MarketSourceError("Tushare 参考缓存状态缺少 files")

    result: dict[str, dict[date, PriceLimitObservation]] = {}
    loaded_files: list[str] = []
    row_count = 0
    for relative, metadata in sorted(files.items()):
        if not isinstance(metadata, dict) or metadata.get("endpoint") != "reference_history":
            continue
        path = (root / str(relative)).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as exc:
            raise MarketSourceError("Tushare 参考缓存路径越界") from exc
        if not path.is_file() or _digest(path) != metadata.get("sha256"):
            raise MarketSourceError(f"Tushare 参考缓存哈希漂移: {relative}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "tushare-reference-history-cache-v1":
            raise MarketSourceError(f"参考历史缓存版本不受支持: {relative}")
        rows = payload.get("rows")
        if not isinstance(rows, list):
            raise MarketSourceError(f"参考历史缓存 rows 无效: {relative}")
        for row in rows:
            if not isinstance(row, dict) or row.get("price_limit_observed") is not True:
                continue
            observed = date.fromisoformat(str(row.get("trading_date")))
            if observed < start or observed > end:
                continue
            security_id = str(row.get("security_id") or "")
            if not security_id:
                raise MarketSourceError(f"参考历史缓存证券无效: {relative}")
            observation = PriceLimitObservation(
                security_id=security_id,
                trading_date=observed,
                limit_up=row.get("limit_up") is True,
                limit_down=row.get("limit_down") is True,
            )
            security_rows = result.setdefault(security_id, {})
            if observed in security_rows and security_rows[observed] != observation:
                raise MarketSourceError(
                    f"参考历史缓存同证券同日涨跌停状态冲突: {security_id} {observed}"
                )
            security_rows[observed] = observation
            row_count += 1
        loaded_files.append(str(relative))
    row_count = sum(len(observations) for observations in result.values())
    return PriceLimitCacheLoad(result, tuple(loaded_files), row_count)


def load_trading_calendar_cache(root: Path, *, start: date, end: date) -> TradingCalendarCacheLoad:
    state_path = root / "state.json"
    if not state_path.is_file():
        return TradingCalendarCacheLoad(frozenset(), frozenset(), ())
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("schema_version") != "tushare-reference-cache-state-v1":
        raise MarketSourceError("Tushare 参考缓存状态版本不受支持")
    files = state.get("files")
    if not isinstance(files, dict):
        raise MarketSourceError("Tushare 参考缓存状态缺少 files")

    # 同一年可能有多次只追加的日历观测；构建时只消费最新且哈希有效的版本。
    selected: dict[int, tuple[datetime, str, dict[str, object]]] = {}
    for relative, metadata in sorted(files.items()):
        if not isinstance(metadata, dict) or metadata.get("endpoint") != "trade_cal":
            continue
        observed = date.fromisoformat(str(metadata.get("observed_date")))
        if observed.year < start.year or observed.year > end.year:
            continue
        fetched_at = datetime.fromisoformat(str(metadata.get("fetched_at")))
        if fetched_at.tzinfo is None:
            raise MarketSourceError(f"trade_cal 缓存时间缺少时区: {relative}")
        current = selected.get(observed.year)
        if current is None or fetched_at > current[0]:
            selected[observed.year] = (fetched_at, str(relative), metadata)

    open_days: set[date] = set()
    session_days: set[date] = set()
    loaded_files: list[str] = []
    for _, relative, metadata in sorted(selected.values(), key=lambda item: item[1]):
        path = (root / relative).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as exc:
            raise MarketSourceError("Tushare 参考缓存路径越界") from exc
        if not path.is_file() or _digest(path) != metadata.get("sha256"):
            raise MarketSourceError(f"Tushare 参考缓存哈希漂移: {relative}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "tushare-trade-calendar-cache-v1":
            raise MarketSourceError(f"trade_cal 缓存版本不受支持: {relative}")
        sessions = payload.get("sessions")
        if not isinstance(sessions, list):
            raise MarketSourceError(f"trade_cal 缓存 sessions 无效: {relative}")
        for row in sessions:
            if not isinstance(row, dict):
                raise MarketSourceError(f"trade_cal 缓存行无效: {relative}")
            session_date = date.fromisoformat(str(row.get("calendar_date")))
            if session_date < start or session_date > end:
                continue
            session_days.add(session_date)
            if row.get("is_open") is True:
                open_days.add(session_date)
        loaded_files.append(relative)
    return TradingCalendarCacheLoad(
        frozenset(open_days), frozenset(session_days), tuple(loaded_files)
    )
