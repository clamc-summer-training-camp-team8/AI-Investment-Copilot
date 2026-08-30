"""量化实验室接口。只执行研究回测，不生成交易或调仓指令。"""

from fastapi import APIRouter, HTTPException

from app.api.deps import ActorDep
from app.calc.backtest import BacktestConfig, BacktestInputError
from app.schemas.quant import QuantBacktestIn, QuantBacktestOut
from app.services.quant import QuantBarInput, QuantSignalInput, run_quant_backtest

router = APIRouter(prefix="/quant", tags=["quant"])


@router.post("/backtests", response_model=QuantBacktestOut)
def create_backtest(payload: QuantBacktestIn, actor: ActorDep) -> QuantBacktestOut:
    del actor  # 身份依赖用于阻止匿名调用；MVP 回测不持久化研究数据。
    try:
        run = run_quant_backtest(
            name=payload.name,
            bars=[
                QuantBarInput(
                    trading_date=item.trading_date,
                    close=item.close,
                    benchmark_close=item.benchmark_close,
                    tradable=item.tradable,
                )
                for item in payload.bars
            ],
            signals=[
                QuantSignalInput(
                    signal_id=item.signal_id,
                    disclosed_at=item.disclosed_at,
                    generated_at=item.generated_at,
                    direction=item.direction,
                    strength=item.strength,
                    confidence=item.confidence,
                )
                for item in payload.signals
            ],
            config=BacktestConfig(
                initial_capital=payload.config.initial_capital,
                holding_days=payload.config.holding_days,
                transaction_cost_bps=payload.config.transaction_cost_bps,
                slippage_bps=payload.config.slippage_bps,
                allow_short=payload.config.allow_short,
            ),
        )
    except (BacktestInputError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return QuantBacktestOut.model_validate(run)
