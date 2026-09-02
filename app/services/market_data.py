"""版本化行情端口与冻结 JSON 适配器。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Protocol, cast

from app.calc.portfolio import PortfolioBar


class MarketDataError(ValueError):
    """冻结行情缺失、漂移或授权状态不满足研究准入。"""


@dataclass(frozen=True)
class CorporateAction:
    action_id: str
    security_id: str
    ex_date: date
    action_type: str
    ratio: Decimal | None
    cash_amount: Decimal | None
    currency: str | None
    source_locator: str


@dataclass(frozen=True)
class MarketDatasetInfo:
    dataset_id: str
    data_version: str
    status: str
    source_policy_id: str
    authorization_status: str
    adjustment: str
    timezone: str
    coverage_start: date
    coverage_end: date
    securities: tuple[str, ...]
    quote_sha256: str
    calendar_sha256: str
    corporate_action_sha256: str
    capabilities: dict[str, bool]
    limitations: tuple[str, ...]


class MarketDataPort(Protocol):
    def info(self) -> MarketDatasetInfo: ...

    def bars(
        self,
        security_ids: tuple[str, ...],
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> list[PortfolioBar]: ...

    def trading_days(self, market: str, *, start: date, end: date) -> tuple[date, ...]: ...

    def corporate_actions(self, security_id: str) -> tuple[CorporateAction, ...]: ...


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class FrozenJsonMarketData:
    """读取冻结副本；任何文件哈希漂移都拒绝回测。"""

    def __init__(self, manifest_path: Path | None = None) -> None:
        if manifest_path is None:
            # 离线行情采集环境只安装 market-data 依赖；仅在调用默认在线配置时
            # 才加载 pydantic-settings，显式清单读取保持最小依赖。
            from app.core.config import settings

            manifest_path = settings.quant_default_market_manifest
        self._manifest_path = manifest_path
        try:
            self._manifest = cast(
                dict[str, object], json.loads(self._manifest_path.read_text(encoding="utf-8"))
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise MarketDataError(f"无法读取冻结行情清单: {self._manifest_path}") from exc
        self._root = self._manifest_path.parent.resolve()
        self._verify_manifest()

    @property
    def manifest_path(self) -> Path:
        return self._manifest_path

    def _asset(self, name: str) -> Path:
        assets = cast(dict[str, dict[str, object]], self._manifest["assets"])
        item = assets[name]
        path = (self._root / str(item["path"])).resolve()
        if self._root not in path.parents:
            raise MarketDataError(f"行情资产越出冻结目录: {name}")
        if not path.is_file():
            raise MarketDataError(f"冻结行情资产不存在: {path}")
        actual = _sha256(path)
        expected = str(item["sha256"])
        if actual != expected:
            raise MarketDataError(
                f"冻结行情资产哈希漂移: {name}, expected={expected}, actual={actual}"
            )
        return path

    def _verify_manifest(self) -> None:
        if self._manifest.get("schema_version") != "frozen-market-dataset-v1":
            raise MarketDataError("不支持的冻结行情清单版本")
        if self._manifest.get("status") != "frozen":
            raise MarketDataError("行情集未冻结")
        authorization = cast(dict[str, object], self._manifest.get("authorization") or {})
        if authorization.get("status") != "公开行情研究使用已核验":
            raise MarketDataError("行情来源未通过研究使用授权核验")
        if self._manifest.get("adjustment") != "前复权":
            raise MarketDataError("当前组合引擎只接受清单明确声明的前复权行情")
        assets = cast(dict[str, dict[str, object]], self._manifest.get("assets") or {})
        required = {"bars", "calendar", "corporate_actions"}
        if not required.issubset(assets):
            raise MarketDataError("冻结行情清单缺少必需资产")
        for name in assets:
            self._asset(name)

    def info(self) -> MarketDatasetInfo:
        assets = cast(dict[str, dict[str, object]], self._manifest["assets"])
        coverage = cast(dict[str, str], self._manifest["coverage"])
        authorization = cast(dict[str, str], self._manifest["authorization"])
        capabilities = cast(dict[str, bool], self._manifest["capabilities"])
        return MarketDatasetInfo(
            dataset_id=str(self._manifest["dataset_id"]),
            data_version=str(self._manifest["data_version"]),
            status=str(self._manifest["status"]),
            source_policy_id=authorization["policy_id"],
            authorization_status=authorization["status"],
            adjustment=str(self._manifest["adjustment"]),
            timezone=str(self._manifest["timezone"]),
            coverage_start=date.fromisoformat(coverage["start"]),
            coverage_end=date.fromisoformat(coverage["end"]),
            securities=tuple(cast(list[str], self._manifest["securities"])),
            quote_sha256=str(assets["bars"]["sha256"]),
            calendar_sha256=str(assets["calendar"]["sha256"]),
            corporate_action_sha256=str(assets["corporate_actions"]["sha256"]),
            capabilities=capabilities,
            limitations=tuple(cast(list[str], self._manifest.get("limitations") or [])),
        )

    def bars(
        self,
        security_ids: tuple[str, ...],
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> list[PortfolioBar]:
        unknown = sorted(set(security_ids) - set(self.info().securities))
        if unknown:
            raise MarketDataError(f"冻结行情集不含证券: {', '.join(unknown)}")
        payload = json.loads(self._asset("bars").read_text(encoding="utf-8"))
        rows = cast(list[dict[str, object]], payload["rows"])
        selected: list[PortfolioBar] = []
        wanted = set(security_ids)
        for row in rows:
            trading_date = date.fromisoformat(str(row["trading_date"]))
            if str(row["security_id"]) not in wanted:
                continue
            if start is not None and trading_date < start:
                continue
            if end is not None and trading_date > end:
                continue
            selected.append(
                PortfolioBar(
                    trading_date=trading_date,
                    security_id=str(row["security_id"]),
                    adjusted_close=Decimal(str(row["adjusted_close"])),
                    benchmark_close=Decimal(str(row["benchmark_close"])),
                    industry=str(row["industry"]),
                    market_cap=(
                        Decimal(str(row["market_cap"]))
                        if row.get("market_cap") is not None
                        else None
                    ),
                    traded_notional=(
                        Decimal(str(row["traded_notional"]))
                        if row.get("traded_notional") is not None
                        else None
                    ),
                    tradable=bool(row.get("tradable", True)),
                    limit_up=bool(row.get("limit_up", False)),
                    limit_down=bool(row.get("limit_down", False)),
                )
            )
        if not selected:
            raise MarketDataError("所选证券和区间没有冻结行情")
        return selected

    def security_metadata(self) -> list[dict[str, object]]:
        """汇总冻结行情中的证券口径，供产品选择器和能力门禁展示。"""

        assets = cast(dict[str, dict[str, object]], self._manifest["assets"])
        names: dict[str, str] = {}
        if "research_universe" in assets:
            universe = cast(
                dict[str, object],
                json.loads(self._asset("research_universe").read_text(encoding="utf-8")),
            )
            members = cast(list[dict[str, object]], universe.get("members") or [])
            names = {
                str(item["security_id"]): str(item["name"])
                for item in members
                if item.get("security_id") and item.get("name")
            }
        payload = json.loads(self._asset("bars").read_text(encoding="utf-8"))
        rows = cast(list[dict[str, object]], payload["rows"])
        grouped: dict[str, dict[str, object]] = {}
        for row in rows:
            security_id = str(row["security_id"])
            trading_date = str(row["trading_date"])
            item = grouped.setdefault(
                security_id,
                {
                    "security_id": security_id,
                    "name": names.get(security_id),
                    "market": str(row.get("market") or "未知"),
                    "currency": str(row.get("currency") or "未知"),
                    "industry": str(row.get("industry") or "未分类"),
                    "benchmark_id": str(row.get("benchmark_id") or ""),
                    "coverage_start": trading_date,
                    "coverage_end": trading_date,
                    "row_count": 0,
                    "market_cap_count": 0,
                },
            )
            item["coverage_start"] = min(str(item["coverage_start"]), trading_date)
            item["coverage_end"] = max(str(item["coverage_end"]), trading_date)
            item["row_count"] = cast(int, item["row_count"]) + 1
            if row.get("market_cap") is not None:
                item["market_cap_count"] = cast(int, item["market_cap_count"]) + 1
        return [
            {
                **item,
                "market_cap_complete": item["market_cap_count"] == item["row_count"],
            }
            for _, item in sorted(grouped.items())
        ]

    def trading_days(self, market: str, *, start: date, end: date) -> tuple[date, ...]:
        payload = json.loads(self._asset("calendar").read_text(encoding="utf-8"))
        markets = cast(dict[str, list[dict[str, object]]], payload["markets"])
        if market not in markets:
            raise MarketDataError(f"冻结交易日历不支持市场: {market}")
        return tuple(
            current
            for row in markets[market]
            if bool(row["is_open"])
            and start <= (current := date.fromisoformat(str(row["date"]))) <= end
        )

    def corporate_actions(self, security_id: str) -> tuple[CorporateAction, ...]:
        payload = json.loads(self._asset("corporate_actions").read_text(encoding="utf-8"))
        rows = cast(list[dict[str, object]], payload["events"])
        return tuple(
            CorporateAction(
                action_id=str(row["action_id"]),
                security_id=str(row["security_id"]),
                ex_date=date.fromisoformat(str(row["ex_date"])),
                action_type=str(row["action_type"]),
                ratio=Decimal(str(row["ratio"])) if row.get("ratio") is not None else None,
                cash_amount=(
                    Decimal(str(row["cash_amount"])) if row.get("cash_amount") is not None else None
                ),
                currency=str(row["currency"]) if row.get("currency") else None,
                source_locator=str(row["source_locator"]),
            )
            for row in rows
            if row["security_id"] == security_id
        )
