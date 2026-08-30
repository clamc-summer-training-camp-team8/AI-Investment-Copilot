"""量化研究服务：把研究信号映射为确定性回测输入。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256

from app.calc.backtest import (
    BacktestConfig,
    BacktestResult,
    MarketBar,
    StrategySignal,
    run_event_backtest,
)
from app.core.timeutil import now

_DIRECTION_SIGN = {"支持": Decimal(1), "冲突": Decimal(-1), "中性": Decimal(0)}
_STRENGTH_WEIGHT = {"高": Decimal(1), "中": Decimal("0.7"), "低": Decimal("0.4")}


@dataclass(frozen=True)
class QuantBarInput:
    trading_date: date
    close: Decimal
    benchmark_close: Decimal
    tradable: bool = True


@dataclass(frozen=True)
class QuantSignalInput:
    signal_id: str
    disclosed_at: datetime
    generated_at: datetime
    direction: str
    strength: str
    confidence: Decimal


@dataclass(frozen=True)
class QuantBacktestRun:
    run_id: str
    name: str
    generated_at: datetime
    result: BacktestResult


def _signal_score(signal: QuantSignalInput) -> Decimal:
    try:
        sign = _DIRECTION_SIGN[signal.direction]
        strength = _STRENGTH_WEIGHT[signal.strength]
    except KeyError as exc:
        raise ValueError(f"未知信号方向或强度: {exc.args[0]}") from exc
    return sign * strength * signal.confidence


def _run_id(
    *,
    name: str,
    bars: list[QuantBarInput],
    signals: list[QuantSignalInput],
    config: BacktestConfig,
) -> str:
    payload = {
        "name": name,
        "bars": [asdict(item) for item in bars],
        "signals": [asdict(item) for item in signals],
        "config": asdict(config),
        "methodology": "event-backtest-v1",
    }
    digest = sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return f"QBT-{digest[:16]}"


def run_quant_backtest(
    *,
    name: str,
    bars: list[QuantBarInput],
    signals: list[QuantSignalInput],
    config: BacktestConfig,
) -> QuantBacktestRun:
    """运行量化回测；相同输入与方法版本产生相同 run_id。"""
    market_bars = [
        MarketBar(
            trading_date=item.trading_date,
            close=item.close,
            benchmark_close=item.benchmark_close,
            tradable=item.tradable,
        )
        for item in bars
    ]
    strategy_signals = [
        StrategySignal(
            signal_id=item.signal_id,
            disclosed_at=item.disclosed_at,
            generated_at=item.generated_at,
            score=_signal_score(item),
        )
        for item in signals
    ]
    result = run_event_backtest(market_bars, strategy_signals, config)
    return QuantBacktestRun(
        run_id=_run_id(name=name, bars=bars, signals=signals, config=config),
        name=name,
        generated_at=now(),
        result=result,
    )
