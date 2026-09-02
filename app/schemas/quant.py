"""研究验证型量化回测 API 契约。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

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


class FrozenSignalIn(QuantSignalIn):
    security_id: Annotated[str, Field(min_length=1, max_length=64)]
    confirmation_status: Literal["已确认"]
    source_evidence_id: Annotated[str, Field(min_length=1, max_length=96)]
    source_relation_id: Annotated[str, Field(min_length=1, max_length=96)]


class FreezeSignalSetIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=255)]
    version: Annotated[str, Field(min_length=1, max_length=96)]
    signals: Annotated[list[FrozenSignalIn], Field(min_length=1, max_length=10000)]


class QuantMarketDatasetOut(_FromAttributes):
    dataset_id: str
    data_version: str
    manifest_sha256: str
    source_policy_id: str
    authorization_status: str
    adjustment: str
    coverage_start: date
    coverage_end: date
    securities: list[str]
    capabilities: dict[str, bool]
    limitations: list[str]
    status: str
    frozen_by: str
    frozen_at: datetime


class QuantSignalSetOut(_FromAttributes):
    signal_set_id: str
    name: str
    version: str
    content_sha256: str
    signal_count: int
    human_confirmed_only: bool
    evaluation_track: str
    status: str
    frozen_by: str
    frozen_at: datetime


class QuantSignalDetailOut(BaseModel):
    signal_id: str
    security_id: str
    disclosed_at: datetime
    generated_at: datetime
    direction: str
    strength: str
    confidence: Decimal
    confirmation_status: str
    source_evidence_id: str
    source_relation_id: str
    source_relation_status: str
    thesis_id: str
    hypothesis_id: str
    source_locator: str
    source_document_id: str | None = None
    source_document_title: str | None = None
    confidence_role: str = "ai_judgement_metadata_only"
    confidence_used_for_alpha_weight: bool = False


class QuantSignalSetDetailOut(QuantSignalSetOut):
    visible_signal_count: int
    signals: list[QuantSignalDetailOut]


class QuantFactorDefinitionOut(_FromAttributes):
    factor_id: str
    name: str
    category: str
    description: str
    formula: str
    frequency: str
    coverage_scope: str
    input_fields: list[str]
    status: str
    version: str
    methodology_version: str
    owner: str
    published_at: date
    deprecated_at: date | None = None
    enabled_by_default: bool
    limitations: list[str]


class QuantModelTemplateOut(_FromAttributes):
    template_id: str
    name: str
    version: str
    status: str
    description: str
    methodology_version: str
    alpha_factor_ids: list[str]
    control_factor_ids: list[str]
    default_config: dict[str, Any]
    required_config: dict[str, Any]
    sample_gate: dict[str, int]
    owner: str
    published_at: date | None = None
    deprecated_at: date | None = None
    limitations: list[str]


class QuantManifestAssetOut(BaseModel):
    name: str
    path: str
    sha256: str
    byte_size: int | None = None
    verified: bool


class QuantSecurityMetadataOut(BaseModel):
    security_id: str
    name: str | None = None
    market: str
    currency: str
    industry: str
    benchmark_id: str
    coverage_start: date
    coverage_end: date
    row_count: int
    market_cap_count: int
    market_cap_complete: bool


class QuantMarketDatasetDetailOut(QuantMarketDatasetOut):
    is_default: bool
    manifest_verified: bool
    assets: list[QuantManifestAssetOut]
    source_priority: list[str]
    authorization_scope: str | None = None
    timezone: str
    adjustment_anchor_date: date | None = None
    available_signal_sets: list[QuantSignalSetOut]
    backtest_count: int
    security_metadata: list[QuantSecurityMetadataOut]


class EvaluationSeparationOut(BaseModel):
    semantic_evaluation: str = "gold_semantic_accuracy"
    retrieval_evaluation: str = "retrieval_ranking_quality"
    alpha_validation: str = "alpha_validation"
    hard_rule: str = "回测收益不得替代金标准确率、检索门禁或人工确认"


class QuantCatalogOut(BaseModel):
    default_market_dataset_id: str | None = None
    market_datasets: list[QuantMarketDatasetOut]
    signal_sets: list[QuantSignalSetOut]
    evaluation_separation: EvaluationSeparationOut = Field(default_factory=EvaluationSeparationOut)


class PortfolioConfigIn(BaseModel):
    initial_capital: Annotated[Decimal, Field(gt=0)] = Decimal("1000000")
    rolling_window_days: Annotated[int, Field(ge=2, le=756)] = 60
    walk_forward_days: Annotated[int, Field(ge=1, le=252)] = 20
    rebalance_days: Annotated[int, Field(ge=1, le=252)] = 5
    transaction_cost_bps: Annotated[Decimal, Field(ge=0, le=1000)] = Decimal(10)
    slippage_bps: Annotated[Decimal, Field(ge=0, le=1000)] = Decimal(5)
    max_security_weight: Annotated[Decimal, Field(gt=0, le=1)] = Decimal("0.20")
    max_industry_weight: Annotated[Decimal, Field(gt=0, le=1)] = Decimal("0.40")
    capacity_participation_rate: Annotated[Decimal, Field(gt=0, le=1)] = Decimal("0.10")
    neutralize_industry: bool = False
    neutralize_market_cap: bool = False
    enforce_capacity: bool = True
    allow_short: bool = True


class PortfolioBacktestIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=255)] = "组合事件信号研究"
    market_dataset_id: Annotated[str, Field(min_length=1, max_length=96)]
    signal_set_id: Annotated[str, Field(min_length=1, max_length=96)]
    model_template_id: Annotated[str, Field(min_length=1, max_length=96)] = (
        "confirmed-event-research-v3"
    )
    security_ids: Annotated[list[str], Field(min_length=1, max_length=1000)]
    start: date | None = None
    end: date | None = None
    config: PortfolioConfigIn = Field(default_factory=PortfolioConfigIn)


class PortfolioBacktestOut(_FromAttributes):
    run_id: str
    name: str
    market_dataset_id: str
    signal_set_id: str
    methodology_version: str
    parameters: dict[str, Any]
    result: dict[str, Any]
    evaluation_track: str
    requested_by: str
    generated_at: datetime


class QuantDemoDatasetOut(BaseModel):
    dataset_id: str
    data_version: str
    manifest_sha256: str
    coverage_start: date
    coverage_end: date
    security_count: int
    trading_day_count: int


class QuantDemoSummaryOut(BaseModel):
    candidate_count: int
    assumed_confirmed_count: int
    directional_signal_count: int
    neutral_noop_count: int
    checkpoint_count: int
    support_count: int
    conflict_count: int


class QuantDemoScoreMappingOut(BaseModel):
    direction: Literal["支持", "冲突", "中性"]
    strength: Literal["高", "中", "低"]
    score: Decimal
    portfolio_effect: str


class QuantDemoDecisionStepOut(BaseModel):
    step: str
    title: str
    description: str


class QuantDemoEventOut(BaseModel):
    signal_id: str
    security_id: str
    security_name: str
    industry: str
    disclosed_at: datetime
    assumed_reviewed_at: datetime
    direction: Literal["支持", "冲突", "中性"]
    strength: Literal["高", "中", "低"]
    score: Decimal
    decision_effect: str
    thesis_title: str
    hypothesis_statement: str
    evidence_title: str


class QuantDemoScenarioOut(BaseModel):
    scenario_id: str
    run_id: str
    title: str
    evaluation_track: Literal["scenario_simulation"]
    scenario_policy_version: str
    methodology_version: str
    generated_at: datetime
    assumption: str
    disclaimer: str
    dataset: QuantDemoDatasetOut
    summary: QuantDemoSummaryOut
    score_mapping: list[QuantDemoScoreMappingOut]
    decision_pipeline: list[QuantDemoDecisionStepOut]
    latest_events: list[QuantDemoEventOut]
    result: dict[str, Any]
