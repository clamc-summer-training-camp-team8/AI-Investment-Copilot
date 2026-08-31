"""研究行情上游连接器。

上游连接器只负责抓取和规范化；在线回测永远读取已经冻结并校验哈希的数据集。
AKShare 是无需 Token 的主源，Tushare 只有在显式提供 Token 时才作为降级和字段补充源。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from importlib import import_module
from statistics import median
from typing import Any, Protocol


class MarketSourceError(RuntimeError):
    """上游行情接口缺失、返回异常或无法规范化。"""


class MarketTarget(Protocol):
    @property
    def security_id(self) -> str: ...

    @property
    def secucode(self) -> str: ...

    @property
    def tencent_symbol(self) -> str: ...

    @property
    def market(self) -> str: ...

    @property
    def is_hk(self) -> bool: ...


@dataclass(frozen=True)
class SourceQuote:
    trading_date: date
    adjusted_open: Decimal
    adjusted_close: Decimal
    adjusted_high: Decimal
    adjusted_low: Decimal
    volume_shares: Decimal | None
    traded_notional: Decimal | None
    source_interface: str
    upstream_provider: str


@dataclass(frozen=True)
class PointInTimeSupplement:
    market_cap: Decimal | None = None
    tradable: bool = True
    limit_up: bool = False
    limit_down: bool = False
    market_cap_observed: bool = False
    price_limit_observed: bool = False


@dataclass(frozen=True)
class SupplementBatch:
    by_date: dict[date, PointInTimeSupplement]
    capabilities: dict[str, bool]
    errors: tuple[str, ...]


@dataclass(frozen=True)
class PermissionProbe:
    endpoint: str
    status: str
    row_count: int
    reason: str | None = None


@dataclass(frozen=True)
class MarketCapObservation:
    security_id: str
    trading_date: date
    total_market_cap: Decimal
    circulating_market_cap: Decimal | None


@dataclass(frozen=True)
class DailyBasicSnapshot:
    trading_date: date
    by_security: dict[str, MarketCapObservation]
    upstream_row_count: int
    missing_security_ids: tuple[str, ...]


@dataclass(frozen=True)
class PriceLimitObservation:
    security_id: str
    trading_date: date
    limit_up: bool
    limit_down: bool


@dataclass(frozen=True)
class TradingCalendarSession:
    calendar_date: date
    is_open: bool
    previous_trading_date: date | None


def _date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").date()
    return date.fromisoformat(text[:10])


def _decimal(value: object, *, required: bool = True) -> Decimal | None:
    if value is None or str(value).strip() in {"", "nan", "None"}:
        if required:
            raise MarketSourceError("行情必填数值为空")
        return None
    result = Decimal(str(value))
    if required and result <= 0:
        raise MarketSourceError(f"行情必填数值必须大于 0: {value}")
    return result


def _records(frame: object, *, label: str) -> list[dict[str, object]]:
    if not hasattr(frame, "to_dict"):
        raise MarketSourceError(f"{label} 未返回 DataFrame")
    rows = frame.to_dict("records")
    if not isinstance(rows, list):
        raise MarketSourceError(f"{label} 返回结构不受支持")
    return rows


def _normalized_rows(
    frame: object,
    *,
    start: date,
    end: date,
    date_field: str,
    open_field: str,
    close_field: str,
    high_field: str,
    low_field: str,
    volume_field: str | None,
    amount_field: str | None,
    volume_multiplier: Decimal,
    amount_multiplier: Decimal,
    source_interface: str,
    upstream_provider: str,
) -> list[SourceQuote]:
    result: list[SourceQuote] = []
    for row in _records(frame, label=source_interface):
        trading_date = _date(row.get(date_field))
        if trading_date < start or trading_date > end:
            continue
        volume = _decimal(row.get(volume_field), required=False) if volume_field else None
        amount = _decimal(row.get(amount_field), required=False) if amount_field else None
        result.append(
            SourceQuote(
                trading_date=trading_date,
                adjusted_open=_decimal(row.get(open_field)) or Decimal(0),
                adjusted_close=_decimal(row.get(close_field)) or Decimal(0),
                adjusted_high=_decimal(row.get(high_field)) or Decimal(0),
                adjusted_low=_decimal(row.get(low_field)) or Decimal(0),
                volume_shares=volume * volume_multiplier if volume is not None else None,
                traded_notional=amount * amount_multiplier if amount is not None else None,
                source_interface=source_interface,
                upstream_provider=upstream_provider,
            )
        )
    result.sort(key=lambda item: item.trading_date)
    if not result:
        raise MarketSourceError(f"{source_interface} 在请求区间没有行情")
    if len({item.trading_date for item in result}) != len(result):
        raise MarketSourceError(f"{source_interface} 返回重复交易日")
    return result


def _normalize_tx_a_volume(rows: list[SourceQuote]) -> list[SourceQuote]:
    """修正腾讯个别深市证券把“手”标作“股”的 100 倍量纲偏差。

    以成交额/成交量得到的隐含均价与收盘价比较；中位比值约 100 时说明成交量仍为手。
    使用全区间中位数，避免单日零量、极端成交或复权价格扰动导致误判。
    """

    ratios = [
        row.traded_notional / row.volume_shares / row.adjusted_close
        for row in rows
        if row.traded_notional is not None
        and row.volume_shares is not None
        and row.volume_shares > 0
        and row.adjusted_close > 0
    ]
    if not ratios or not Decimal(20) <= median(ratios) <= Decimal(200):
        return rows
    return [
        replace(
            row,
            volume_shares=(
                row.volume_shares * Decimal(100) if row.volume_shares is not None else None
            ),
            source_interface=f"{row.source_interface}.volume_x100",
        )
        for row in rows
    ]


class AksharePrimarySource:
    """AKShare 免费研究主源。

    当前选择经过本项目网络验证的子接口：A 股和指数使用腾讯接口，港股使用新浪接口。
    这既保留 AKShare 的统一接入方式，也明确记录其实际上游，避免把聚合库误写成原始来源。
    """

    source_id = "akshare-research-primary-v1"

    def __init__(self, module: object | None = None) -> None:
        try:
            self._module: Any = module or import_module("akshare")
        except ImportError as exc:
            raise MarketSourceError(
                "未安装 AKShare；请先安装 requirements-market-data.txt"
            ) from exc
        self.library_version = str(getattr(self._module, "__version__", "unknown"))

    def equity_quotes(self, target: MarketTarget, *, start: date, end: date) -> list[SourceQuote]:
        if target.is_hk:
            frame = self._module.stock_hk_daily(
                symbol=target.security_id,
                adjust="qfq",
            )
            return _normalized_rows(
                frame,
                start=start,
                end=end,
                date_field="date",
                open_field="open",
                close_field="close",
                high_field="high",
                low_field="low",
                volume_field="volume",
                amount_field="amount",
                volume_multiplier=Decimal(1),
                amount_multiplier=Decimal(1),
                source_interface="akshare.stock_hk_daily",
                upstream_provider="Sina Finance",
            )
        frame = self._module.stock_zh_a_hist_tx(
            symbol=target.tencent_symbol,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust="qfq",
            timeout=30,
        )
        return _normalize_tx_a_volume(
            _normalized_rows(
                frame,
                start=start,
                end=end,
                date_field="date",
                open_field="open",
                close_field="close",
                high_field="high",
                low_field="low",
                volume_field="volume",
                amount_field="amount",
                volume_multiplier=Decimal(1),
                amount_multiplier=Decimal(1),
                source_interface="akshare.stock_zh_a_hist_tx",
                upstream_provider="Tencent Finance",
            )
        )

    def a_share_raw_quotes(
        self, target: MarketTarget, *, start: date, end: date
    ) -> list[SourceQuote]:
        """抓取 A 股未复权序列，专供第二数据源对账，不进入前复权回测。"""

        if target.market != "A股":
            raise MarketSourceError("AKShare 未复权跨源核验当前只覆盖 A 股")
        frame = self._module.stock_zh_a_hist_tx(
            symbol=target.tencent_symbol,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust="",
            timeout=30,
        )
        return _normalize_tx_a_volume(
            _normalized_rows(
                frame,
                start=start,
                end=end,
                date_field="date",
                open_field="open",
                close_field="close",
                high_field="high",
                low_field="low",
                volume_field="volume",
                amount_field="amount",
                volume_multiplier=Decimal(1),
                amount_multiplier=Decimal(1),
                source_interface="akshare.stock_zh_a_hist_tx.raw",
                upstream_provider="Tencent Finance",
            )
        )

    def benchmark_quotes(
        self, target: MarketTarget, *, start: date, end: date
    ) -> list[SourceQuote]:
        frame = self._module.stock_zh_index_daily_tx(
            symbol=target.tencent_symbol,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
        return _normalized_rows(
            frame,
            start=start,
            end=end,
            date_field="date",
            open_field="open",
            close_field="close",
            high_field="high",
            low_field="low",
            volume_field=None,
            amount_field="amount",
            volume_multiplier=Decimal(1),
            amount_multiplier=Decimal(1),
            source_interface="akshare.stock_zh_index_daily_tx",
            upstream_provider="Tencent Finance",
        )


class TushareSupplementSource:
    """可选 Tushare 降级与点时字段补充源；未提供 Token 时不得实例化。"""

    source_id = "tushare-optional-supplement-v1"

    def __init__(
        self,
        token: str,
        module: object | None = None,
        *,
        api_url: str | None = None,
    ) -> None:
        if not token.strip():
            raise MarketSourceError("Tushare Token 为空")
        try:
            self._module: Any = module or import_module("tushare")
        except ImportError as exc:
            raise MarketSourceError(
                "未安装 Tushare；请先安装 requirements-market-data.txt"
            ) from exc
        self.library_version = str(getattr(self._module, "__version__", "unknown"))
        self._token = token
        set_token = getattr(self._module, "set_token", None)
        if callable(set_token):
            set_token(token)
        self._pro = self._module.pro_api(token)
        if api_url is not None:
            from app.ingest.market_source_secrets import validate_tushare_api_url

            validated_api_url = validate_tushare_api_url(api_url)
            self._pro._DataApi__http_url = validated_api_url
        self.api_origin = str(getattr(self._pro, "_DataApi__http_url", "tushare-sdk-default"))
        self.source_id = (
            "tushare-compatible-supplement-v1"
            if api_url is not None
            else "tushare-optional-supplement-v1"
        )
        self.upstream_provider = (
            "Tushare-compatible configured API" if api_url is not None else "Tushare Pro"
        )

    def _safe_error(self, exc: Exception) -> str:
        # 延迟导入以避免 secrets 模块和本模块在类型定义阶段形成循环依赖。
        from app.ingest.market_source_secrets import sanitize_secret_text

        return sanitize_secret_text(f"{type(exc).__name__}: {exc}", secrets=(self._token,))

    def daily_a_share_quotes(
        self, target: MarketTarget, *, start: date, end: date
    ) -> list[SourceQuote]:
        """读取 120 积分可用的 A 股未复权日线，仅用于跨源质量核验。"""

        if target.market != "A股":
            raise MarketSourceError("Tushare daily 当前只用于 A 股跨源核验")
        frame = self._pro.daily(
            ts_code=target.secucode,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            fields="ts_code,trade_date,open,high,low,close,vol,amount",
        )
        return _normalized_rows(
            frame,
            start=start,
            end=end,
            date_field="trade_date",
            open_field="open",
            close_field="close",
            high_field="high",
            low_field="low",
            volume_field="vol",
            amount_field="amount",
            volume_multiplier=Decimal(100),
            amount_multiplier=Decimal(1000),
            source_interface="tushare.daily",
            upstream_provider=self.upstream_provider,
        )

    def a_share_trading_days(self, *, start: date, end: date) -> set[date]:
        return {
            item.calendar_date
            for item in self.a_share_calendar(start=start, end=end)
            if item.is_open
        }

    def a_share_calendar(self, *, start: date, end: date) -> tuple[TradingCalendarSession, ...]:
        frame = self._pro.trade_cal(
            exchange="SSE",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            fields="exchange,cal_date,is_open,pretrade_date",
        )
        result = []
        for row in _records(frame, label="tushare.trade_cal"):
            previous = row.get("pretrade_date")
            result.append(
                TradingCalendarSession(
                    calendar_date=_date(row.get("cal_date")),
                    is_open=str(row.get("is_open")) == "1",
                    previous_trading_date=(
                        _date(previous) if previous is not None and str(previous).strip() else None
                    ),
                )
            )
        result.sort(key=lambda item: item.calendar_date)
        if not result:
            raise MarketSourceError("tushare.trade_cal 在请求区间没有返回日历")
        return tuple(result)

    def daily_basic_snapshot(
        self, targets: tuple[MarketTarget, ...], *, trading_date: date
    ) -> DailyBasicSnapshot:
        """单次按交易日拉取全市场快照，再只保留研究范围证券。"""

        a_targets = {target.secucode: target for target in targets if target.market == "A股"}
        frame = self._pro.daily_basic(
            trade_date=trading_date.strftime("%Y%m%d"),
            fields="ts_code,trade_date,total_mv,circ_mv",
        )
        rows = _records(frame, label="tushare.daily_basic")
        result: dict[str, MarketCapObservation] = {}
        for row in rows:
            code = str(row.get("ts_code") or "")
            target = a_targets.get(code)
            if target is None:
                continue
            total_mv = _decimal(row.get("total_mv"), required=False)
            if total_mv is None:
                continue
            circulating_mv = _decimal(row.get("circ_mv"), required=False)
            result[target.security_id] = MarketCapObservation(
                security_id=target.security_id,
                trading_date=_date(row.get("trade_date")),
                total_market_cap=total_mv * Decimal(10000),
                circulating_market_cap=(
                    circulating_mv * Decimal(10000) if circulating_mv is not None else None
                ),
            )
        missing = tuple(
            sorted(
                target.security_id
                for target in a_targets.values()
                if target.security_id not in result
            )
        )
        return DailyBasicSnapshot(
            trading_date=trading_date,
            by_security=result,
            upstream_row_count=len(rows),
            missing_security_ids=missing,
        )

    def daily_basic_history(
        self, target: MarketTarget, *, start: date, end: date
    ) -> tuple[MarketCapObservation, ...]:
        """单证券单次拉取区间点时市值，用于显式高权限历史回填。"""

        if target.market != "A股":
            raise MarketSourceError("Tushare daily_basic 历史回填当前只覆盖 A 股")
        frame = self._pro.daily_basic(
            ts_code=target.secucode,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            fields="ts_code,trade_date,total_mv,circ_mv",
        )
        result = []
        for row in _records(frame, label="tushare.daily_basic.history"):
            total_mv = _decimal(row.get("total_mv"), required=False)
            if total_mv is None:
                continue
            circulating_mv = _decimal(row.get("circ_mv"), required=False)
            result.append(
                MarketCapObservation(
                    security_id=target.security_id,
                    trading_date=_date(row.get("trade_date")),
                    total_market_cap=total_mv * Decimal(10000),
                    circulating_market_cap=(
                        circulating_mv * Decimal(10000) if circulating_mv is not None else None
                    ),
                )
            )
        result.sort(key=lambda item: item.trading_date)
        if not result:
            raise MarketSourceError(f"tushare.daily_basic.history 未返回 {target.security_id} 数据")
        return tuple(result)

    def price_limit_history(
        self, target: MarketTarget, *, start: date, end: date
    ) -> tuple[PriceLimitObservation, ...]:
        """以未复权收盘价和官方涨跌停价生成逐日可审计状态。"""

        if target.market != "A股":
            raise MarketSourceError("Tushare stk_limit 历史回填当前只覆盖 A 股")
        start_text, end_text = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
        daily = self._pro.daily(
            ts_code=target.secucode,
            start_date=start_text,
            end_date=end_text,
            fields="ts_code,trade_date,close",
        )
        limits = self._pro.stk_limit(
            ts_code=target.secucode,
            start_date=start_text,
            end_date=end_text,
            fields="ts_code,trade_date,up_limit,down_limit",
        )
        close_by_day = {
            _date(row.get("trade_date")): close
            for row in _records(daily, label="tushare.daily.limit_history")
            if (close := _decimal(row.get("close"), required=False)) is not None
        }
        result = []
        for row in _records(limits, label="tushare.stk_limit.history"):
            trading_date = _date(row.get("trade_date"))
            close = close_by_day.get(trading_date)
            up = _decimal(row.get("up_limit"), required=False)
            down = _decimal(row.get("down_limit"), required=False)
            if close is None or up is None or down is None:
                continue
            result.append(
                PriceLimitObservation(
                    security_id=target.security_id,
                    trading_date=trading_date,
                    limit_up=close == up,
                    limit_down=close == down,
                )
            )
        result.sort(key=lambda item: item.trading_date)
        if not result:
            raise MarketSourceError(f"tushare.stk_limit.history 未返回 {target.security_id} 数据")
        return tuple(result)

    def probe_permissions(
        self, target: MarketTarget, *, trading_date: date
    ) -> tuple[PermissionProbe, ...]:
        """以单证券单日最小查询探测产品所需接口，不持久化任何凭证。"""

        day = trading_date.strftime("%Y%m%d")
        calls = {
            "daily": lambda: self._pro.daily(
                ts_code=target.secucode,
                trade_date=day,
                fields="ts_code,trade_date,close,vol,amount",
            ),
            "pro_bar": lambda: self._module.pro_bar(
                api=self._pro,
                ts_code=target.secucode,
                start_date=day,
                end_date=day,
                adj="qfq",
                freq="D",
            ),
            "daily_basic": lambda: self._pro.daily_basic(
                ts_code=target.secucode,
                trade_date=day,
                fields="ts_code,trade_date,total_mv",
            ),
            "stk_limit": lambda: self._pro.stk_limit(
                ts_code=target.secucode,
                trade_date=day,
                fields="ts_code,trade_date,up_limit,down_limit",
            ),
            "trade_cal": lambda: self._pro.trade_cal(
                exchange="SSE",
                start_date=day,
                end_date=day,
                fields="exchange,cal_date,is_open",
            ),
        }
        results: list[PermissionProbe] = []
        for endpoint, call in calls.items():
            try:
                rows = _records(call(), label=f"tushare.{endpoint}")
                results.append(
                    PermissionProbe(
                        endpoint=endpoint,
                        status="available" if rows else "available_empty",
                        row_count=len(rows),
                    )
                )
            except Exception as exc:  # SDK 对权限和网络错误均使用异常表达
                reason = self._safe_error(exc)
                normalized = reason.lower()
                status = (
                    "permission_denied"
                    if any(marker in normalized for marker in ("权限", "积分", "permission"))
                    else "error"
                )
                results.append(PermissionProbe(endpoint, status, 0, reason))
        return tuple(results)

    def fallback_a_share_quotes(
        self, target: MarketTarget, *, start: date, end: date
    ) -> list[SourceQuote]:
        if target.market != "A股":
            raise MarketSourceError("当前 Tushare 行情降级只覆盖 A 股")
        frame = self._module.pro_bar(
            api=self._pro,
            ts_code=target.secucode,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adj="qfq",
            freq="D",
        )
        return _normalized_rows(
            frame,
            start=start,
            end=end,
            date_field="trade_date",
            open_field="open",
            close_field="close",
            high_field="high",
            low_field="low",
            volume_field="vol",
            amount_field="amount",
            volume_multiplier=Decimal(100),
            amount_multiplier=Decimal(1000),
            source_interface="tushare.pro_bar",
            upstream_provider=self.upstream_provider,
        )

    def a_share_supplements(
        self,
        target: MarketTarget,
        *,
        start: date,
        end: date,
        enabled_endpoints: frozenset[str] | None = None,
    ) -> SupplementBatch:
        if target.market != "A股":
            return SupplementBatch({}, {}, ("港股点时补充未启用",))
        start_text, end_text = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
        values: dict[date, PointInTimeSupplement] = {}
        errors: list[str] = []
        capabilities = {
            "point_in_time_market_cap": False,
            "price_limit_status": False,
        }

        enabled = enabled_endpoints or frozenset({"daily", "daily_basic", "stk_limit"})

        if "daily_basic" in enabled:
            try:
                frame = self._pro.daily_basic(
                    ts_code=target.secucode,
                    start_date=start_text,
                    end_date=end_text,
                    fields="ts_code,trade_date,total_mv",
                )
                for row in _records(frame, label="tushare.daily_basic"):
                    day = _date(row.get("trade_date"))
                    total_mv = _decimal(row.get("total_mv"), required=False)
                    if total_mv is not None:
                        values[day] = PointInTimeSupplement(
                            market_cap=total_mv * Decimal(10000), market_cap_observed=True
                        )
                capabilities["point_in_time_market_cap"] = bool(values)
            except Exception as exc:  # Tushare 用权限错误和网络错误统一抛异常
                errors.append(f"daily_basic 不可用: {self._safe_error(exc)}")

        raw_close: dict[date, Decimal] = {}
        limits: dict[date, tuple[Decimal, Decimal]] = {}
        if {"daily", "stk_limit"}.issubset(enabled):
            try:
                daily = self._pro.daily(
                    ts_code=target.secucode,
                    start_date=start_text,
                    end_date=end_text,
                    fields="ts_code,trade_date,close",
                )
                for row in _records(daily, label="tushare.daily"):
                    close = _decimal(row.get("close"), required=False)
                    if close is not None:
                        raw_close[_date(row.get("trade_date"))] = close
                limit_frame = self._pro.stk_limit(
                    ts_code=target.secucode,
                    start_date=start_text,
                    end_date=end_text,
                    fields="ts_code,trade_date,up_limit,down_limit",
                )
                for row in _records(limit_frame, label="tushare.stk_limit"):
                    up = _decimal(row.get("up_limit"), required=False)
                    down = _decimal(row.get("down_limit"), required=False)
                    if up is not None and down is not None:
                        limits[_date(row.get("trade_date"))] = (up, down)
                for day, close in raw_close.items():
                    if day not in limits:
                        continue
                    current = values.get(day, PointInTimeSupplement())
                    up, down = limits[day]
                    values[day] = PointInTimeSupplement(
                        market_cap=current.market_cap,
                        tradable=current.tradable,
                        limit_up=close == up,
                        limit_down=close == down,
                        market_cap_observed=current.market_cap_observed,
                        price_limit_observed=True,
                    )
                capabilities["price_limit_status"] = bool(raw_close) and bool(limits)
            except Exception as exc:
                errors.append(f"涨跌停补充不可用: {self._safe_error(exc)}")

        return SupplementBatch(values, capabilities, tuple(errors))
