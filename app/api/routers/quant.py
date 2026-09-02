"""量化实验室接口。只执行研究回测，不生成交易或调仓指令。"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import ActorDep, SettingsDep, UowDep
from app.calc.backtest import BacktestConfig, BacktestInputError
from app.calc.portfolio import PortfolioConfig, PortfolioInputError
from app.schemas.quant import (
    FreezeSignalSetIn,
    PortfolioBacktestIn,
    PortfolioBacktestOut,
    QuantBacktestIn,
    QuantBacktestOut,
    QuantCatalogOut,
    QuantDemoScenarioOut,
    QuantFactorDefinitionOut,
    QuantMarketDatasetDetailOut,
    QuantMarketDatasetOut,
    QuantModelTemplateOut,
    QuantSignalSetDetailOut,
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
    quant_factor_catalog,
    quant_model_templates,
    register_default_market_dataset,
    run_quant_backtest,
    run_versioned_portfolio_backtest,
    signal_set_detail,
)
from app.services.quant_demo import build_quant_demo_scenario


def require_quant_enabled(settings: SettingsDep) -> None:
    if not settings.quant_research_enabled:
        raise HTTPException(status_code=404, detail="模型与因子模块未启用")


router = APIRouter(
    prefix="/quant",
    tags=["quant"],
    dependencies=[Depends(require_quant_enabled)],
)


@router.get("/demo-scenario", response_model=QuantDemoScenarioOut)
def get_demo_scenario(actor: ActorDep, settings: SettingsDep) -> QuantDemoScenarioOut:
    """Return the deterministic defence scenario without mutating research data."""

    del actor
    if not settings.quant_demo_enabled:
        raise HTTPException(status_code=404, detail="量化答辩演示情景未启用")
    try:
        scenario = build_quant_demo_scenario(settings.quant_default_market_manifest)
    except (PortfolioInputError, MarketDataError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return QuantDemoScenarioOut.model_validate(scenario)


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
def register_market_dataset(
    uow: UowDep,
    actor: ActorDep,
    settings: SettingsDep,
) -> QuantMarketDatasetOut:
    governance_teams = {
        item.strip() for item in settings.quant_governance_teams.split(",") if item.strip()
    }
    if not settings.quant_dataset_api_registration_enabled or (
        not actor.is_admin and actor.teams.isdisjoint(governance_teams)
    ):
        raise HTTPException(status_code=403, detail="冻结行情登记仅限受控数据治理流程")
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


@router.get("/factors", response_model=list[QuantFactorDefinitionOut])
def get_factors(actor: ActorDep) -> list[QuantFactorDefinitionOut]:
    del actor
    return [QuantFactorDefinitionOut.model_validate(item) for item in quant_factor_catalog()]


@router.get("/model-templates", response_model=list[QuantModelTemplateOut])
def get_model_templates(actor: ActorDep) -> list[QuantModelTemplateOut]:
    del actor
    return [QuantModelTemplateOut.model_validate(item) for item in quant_model_templates()]


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


@router.get("/signal-sets/{signal_set_id}", response_model=QuantSignalSetDetailOut)
def get_signal_set_detail(
    signal_set_id: str,
    uow: UowDep,
    actor: ActorDep,
) -> QuantSignalSetDetailOut:
    try:
        result = signal_set_detail(uow, signal_set_id=signal_set_id, actor=actor)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    record = QuantSignalSetOut.model_validate(result["record"])
    return QuantSignalSetDetailOut(
        **record.model_dump(), **{k: v for k, v in result.items() if k != "record"}
    )


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
            model_template_id=payload.model_template_id,
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
