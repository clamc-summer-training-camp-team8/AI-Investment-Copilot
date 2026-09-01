"""P2 涨跌停缺口的交易所规则推导资产读取和硬门禁。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PRICE_LIMIT_DERIVATIONS_PATH = (
    PROJECT_ROOT
    / "analytics"
    / "datasets"
    / "quant-p2-a-share-v1"
    / "price_limit_derivations.json"
)


@dataclass(frozen=True)
class QuantPriceLimitDerivation:
    security_id: str
    trading_date: date
    board: str
    listing_date: date
    pre_close: Decimal
    close: Decimal
    traded_notional: Decimal
    limit_rate: Decimal
    upper_limit: Decimal
    lower_limit: Decimal
    limit_up: bool
    limit_down: bool


@dataclass(frozen=True)
class QuantPriceLimitDerivationSet:
    derivation_set_id: str
    status: str
    rule_id: str
    source_url: str
    rows: tuple[QuantPriceLimitDerivation, ...]
    payload: dict[str, object]
    sha256: str


def _decimal(row: dict[str, object], key: str) -> Decimal:
    try:
        return Decimal(str(row[key]))
    except (KeyError, ArithmeticError) as exc:
        raise ValueError(f"涨跌停推导行缺少有效 {key}") from exc


def load_quant_price_limit_derivations(
    path: Path = DEFAULT_PRICE_LIMIT_DERIVATIONS_PATH,
) -> QuantPriceLimitDerivationSet:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("涨跌停推导资产必须是 JSON 对象")
    payload = cast(dict[str, object], payload)
    if payload.get("schema_version") != "quant-price-limit-derivation-set-v1":
        raise ValueError("涨跌停推导资产版本不受支持")
    if payload.get("status") != "engineering_verified":
        raise ValueError("涨跌停推导资产未通过工程核验")
    frozen_at = datetime.fromisoformat(str(payload["frozen_at"]))
    if frozen_at.tzinfo is None:
        raise ValueError("涨跌停推导资产 frozen_at 必须包含时区")
    if payload.get("method") != "exchange_rule_deterministic":
        raise ValueError("涨跌停缺口只允许确定性交易所规则推导")
    if payload.get("tick_size") != "0.01" or payload.get("rounding") != "ROUND_HALF_UP":
        raise ValueError("涨跌停价必须按 0.01 元和 ROUND_HALF_UP 处理")
    rule = cast(dict[str, object], payload.get("rule") or {})
    effective_from = date.fromisoformat(str(rule["effective_from"]))
    contract = cast(dict[str, object], payload.get("input_contract") or {})
    if contract.get("direct_observation_available") is not False:
        raise ValueError("直接观测可用时禁止用规则推导覆盖")

    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("涨跌停推导资产不能为空")
    rows: list[QuantPriceLimitDerivation] = []
    seen: set[tuple[str, date]] = set()
    for raw in raw_rows:
        if not isinstance(raw, dict):
            raise ValueError("涨跌停推导行必须是 JSON 对象")
        row = cast(dict[str, object], raw)
        security_id = str(row.get("security_id") or "")
        trading_date = date.fromisoformat(str(row["trading_date"]))
        board = str(row.get("board") or "")
        listing_date = date.fromisoformat(str(row["listing_date"]))
        if len(security_id) != 6 or not security_id.isdigit():
            raise ValueError(f"涨跌停推导证券代码无效: {security_id}")
        key = (security_id, trading_date)
        if key in seen:
            raise ValueError(f"涨跌停推导键重复: {security_id} {trading_date}")
        seen.add(key)
        if trading_date < effective_from:
            raise ValueError(f"涨跌停推导日早于规则生效日: {security_id}")
        if listing_date > trading_date - timedelta(days=7):
            raise ValueError(f"无法排除上市前五个交易日无涨跌幅限制: {security_id}")
        expected_board = "SSE_STAR" if security_id.startswith("688") else "SSE_MAIN"
        expected_rate = Decimal("0.20") if expected_board == "SSE_STAR" else Decimal("0.10")
        limit_rate = _decimal(row, "limit_rate")
        if board != expected_board or limit_rate != expected_rate:
            raise ValueError(f"涨跌停板块或比例错误: {security_id}")
        if (
            row.get("daily_trade_status") != "normal"
            or row.get("corporate_action_on_date") is not False
            or row.get("stk_limit_observed") is not False
        ):
            raise ValueError(f"涨跌停推导前置审计未通过: {security_id}")
        pre_close = _decimal(row, "pre_close")
        close = _decimal(row, "close")
        traded_notional = _decimal(row, "traded_notional")
        upper_limit = _decimal(row, "upper_limit")
        lower_limit = _decimal(row, "lower_limit")
        expected_upper = (pre_close * (Decimal(1) + limit_rate)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        expected_lower = (pre_close * (Decimal(1) - limit_rate)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        limit_up = row.get("limit_up") is True
        limit_down = row.get("limit_down") is True
        if upper_limit != expected_upper or lower_limit != expected_lower:
            raise ValueError(f"涨跌停价与交易所规则不一致: {security_id}")
        if limit_up != (close == upper_limit) or limit_down != (close == lower_limit):
            raise ValueError(f"涨跌停状态与收盘价不一致: {security_id}")
        if (
            pre_close <= 0
            or close <= 0
            or traded_notional <= 0
            or (limit_up and limit_down)
        ):
            raise ValueError(f"涨跌停推导数值无效: {security_id}")
        rows.append(
            QuantPriceLimitDerivation(
                security_id=security_id,
                trading_date=trading_date,
                board=board,
                listing_date=listing_date,
                pre_close=pre_close,
                close=close,
                traded_notional=traded_notional,
                limit_rate=limit_rate,
                upper_limit=upper_limit,
                lower_limit=lower_limit,
                limit_up=limit_up,
                limit_down=limit_down,
            )
        )
    rows.sort(key=lambda item: (item.trading_date, item.security_id))
    return QuantPriceLimitDerivationSet(
        derivation_set_id=str(payload["derivation_set_id"]),
        status=str(payload["status"]),
        rule_id=str(rule["rule_id"]),
        source_url=str(rule["source_url"]),
        rows=tuple(rows),
        payload=payload,
        sha256=sha256(path.read_bytes()).hexdigest(),
    )
