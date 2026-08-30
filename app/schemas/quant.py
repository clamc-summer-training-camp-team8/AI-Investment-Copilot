"""研究验证型量化回测 API 契约。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class QuantBarIn(BaseModel):
    trading_date: date
    close: Annotated[Decimal, Field(gt=0)]
    benchmark_close: Annotated[Decimal, Field(gt=0)]
    tradable: bool = True


class QuantSignalIn(BaseModel):
    signal_id: Annotated[str, Field(min_length=1, max_length=100)]
    disclosed_at: datetime
    generated_at: datetime
    direction: Literal["支持", "冲突", "中性"]
    strength: Literal["高", "中", "低"] = "中"
    confidence: Annotated[Decimal, Field(ge=0, le=1)] = Decimal(1)

    @field_validator("disclosed_at", "generated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("时间必须包含时区")
        return value


class QuantConfigIn(BaseModel):
    initial_capital: Annotated[Decimal, Field(gt=0, le=Decimal("1000000000000"))] = Decimal(
        "1000000"
    )
    holding_days: Annotated[int, Field(ge=1, le=252)] = 20
    transaction_cost_bps: Annotated[Decimal, Field(ge=0, le=1000)] = Decimal(10)
    slippage_bps: Annotated[Decimal, Field(ge=0, le=1000)] = Decimal(5)
    allow_short: bool = False


class QuantBacktestIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=100)] = "事件方向信号研究"
    bars: Annotated[list[QuantBarIn], Field(min_length=3, max_length=5000)]
    signals: Annotated[list[QuantSignalIn], Field(min_length=1, max_length=1000)]
    config: QuantConfigIn = Field(default_factory=QuantConfigIn)


class _FromAttributes(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class QuantMetricsOut(_FromAttributes):
    initial_capital: Decimal
    final_equity: Decimal
    total_return: Decimal
    benchmark_return: Decimal
    excess_return: Decimal
    annualized_return: Decimal
    annualized_volatility: Decimal
    sharpe_ratio: Decimal | None
    max_drawdown: Decimal
    win_rate: Decimal | None
    turnover: Decimal
    trade_count: int
    average_exposure: Decimal


class QuantEquityPointOut(_FromAttributes):
    trading_date: date
    equity: Decimal
    benchmark_equity: Decimal
    drawdown: Decimal
    position: Decimal


class QuantTradeOut(_FromAttributes):
    signal_id: str
    direction: str
    entry_date: date
    exit_date: date
    entry_price: Decimal
    exit_price: Decimal
    position: Decimal
    gross_return: Decimal
    net_return: Decimal
    holding_days: int
    exit_reason: str


class QuantDiagnosticsOut(_FromAttributes):
    input_signal_count: int
    accepted_signal_count: int
    skipped_signal_count: int
    skipped_signals: tuple[str, ...]
    warnings: tuple[str, ...]


class QuantResultOut(_FromAttributes):
    metrics: QuantMetricsOut
    equity_curve: tuple[QuantEquityPointOut, ...]
    trades: tuple[QuantTradeOut, ...]
    diagnostics: QuantDiagnosticsOut
    methodology_version: str


class QuantBacktestOut(_FromAttributes):
    run_id: str
    name: str
    generated_at: datetime
    result: QuantResultOut
