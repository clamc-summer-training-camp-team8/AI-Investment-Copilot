"""量化实验室接口。只执行研究回测，不生成交易或调仓指令。"""

from fastapi import APIRouter, HTTPException

from app.api.deps import ActorDep, UowDep
from app.calc.backtest import BacktestConfig, BacktestInputError
from app.calc.portfolio import PortfolioConfig, PortfolioInputError
from app.schemas.quant import (
    FreezeSignalSetIn,
    PortfolioBacktestIn,
    PortfolioBacktestOut,
    QuantBacktestIn,
    QuantBacktestOut,
    QuantCatalogOut,
    QuantMarketDatasetDetailOut,
    QuantMarketDatasetOut,
    QuantSignalSetOut,
)
from app.services.market_data import MarketDataError
from app.services.quant import (
    FrozenSignalInput,
    QuantBarInput,
    QuantSignalInput,
    configured_default_market_dataset_id,
    freeze_signal_set,
    market_dataset_detail,
    register_default_market_dataset,
    run_quant_backtest,
    run_versioned_portfolio_backtest,
)

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


@router.post("/market-datasets/register-default", response_model=QuantMarketDatasetOut)
def register_market_dataset(uow: UowDep, actor: ActorDep) -> QuantMarketDatasetOut:
    try:
        record = register_default_market_dataset(uow, frozen_by=actor.user_id)
    except MarketDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return QuantMarketDatasetOut.model_validate(record)


@router.get("/catalog", response_model=QuantCatalogOut)
def get_catalog(uow: UowDep, actor: ActorDep) -> QuantCatalogOut:
    del actor
    return QuantCatalogOut(
        default_market_dataset_id=configured_default_market_dataset_id(uow),
        market_datasets=[
            QuantMarketDatasetOut.model_validate(item) for item in uow.quant.list_market_datasets()
        ],
        signal_sets=[
            QuantSignalSetOut.model_validate(item) for item in uow.quant.list_signal_sets()
        ],
    )


@router.get("/market-datasets/{dataset_id}", response_model=QuantMarketDatasetDetailOut)
def get_market_dataset_detail(
    dataset_id: str, uow: UowDep, actor: ActorDep
) -> QuantMarketDatasetDetailOut:
    try:
        result = market_dataset_detail(uow, dataset_id=dataset_id, requested_by=actor.user_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MarketDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record = QuantMarketDatasetOut.model_validate(result.pop("record"))
    return QuantMarketDatasetDetailOut(**record.model_dump(), **result)


@router.post("/signal-sets", response_model=QuantSignalSetOut)
def create_signal_set(
    payload: FreezeSignalSetIn, uow: UowDep, actor: ActorDep
) -> QuantSignalSetOut:
    try:
        record = freeze_signal_set(
            uow,
            name=payload.name,
            version=payload.version,
            signals=[
                FrozenSignalInput(
                    signal_id=item.signal_id,
                    security_id=item.security_id,
                    disclosed_at=item.disclosed_at,
                    generated_at=item.generated_at,
                    direction=item.direction,
                    strength=item.strength,
                    confidence=item.confidence,
                    confirmation_status=item.confirmation_status,
                    source_evidence_id=item.source_evidence_id,
                    source_relation_id=item.source_relation_id,
                )
                for item in payload.signals
            ],
            frozen_by=actor.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return QuantSignalSetOut.model_validate(record)


@router.post("/portfolio-backtests", response_model=PortfolioBacktestOut)
def create_portfolio_backtest(
    payload: PortfolioBacktestIn, uow: UowDep, actor: ActorDep
) -> PortfolioBacktestOut:
    config = PortfolioConfig(**payload.config.model_dump())
    try:
        record = run_versioned_portfolio_backtest(
            uow,
            name=payload.name,
            market_dataset_id=payload.market_dataset_id,
            signal_set_id=payload.signal_set_id,
            security_ids=tuple(payload.security_ids),
            start=payload.start,
            end=payload.end,
            config=config,
            requested_by=actor.user_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (PortfolioInputError, MarketDataError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PortfolioBacktestOut.model_validate(record)


@router.get("/portfolio-backtests", response_model=list[PortfolioBacktestOut])
def list_portfolio_backtests(uow: UowDep, actor: ActorDep) -> list[PortfolioBacktestOut]:
    return [
        PortfolioBacktestOut.model_validate(item)
        for item in uow.quant.list_backtests(actor.user_id)
    ]


@router.get("/portfolio-backtests/{run_id}", response_model=PortfolioBacktestOut)
def get_portfolio_backtest(run_id: str, uow: UowDep, actor: ActorDep) -> PortfolioBacktestOut:
    record = uow.quant.get_backtest(run_id)
    if record is None or record.requested_by != actor.user_id:
        raise HTTPException(status_code=404, detail="组合回测不存在")
    return PortfolioBacktestOut.model_validate(record)
