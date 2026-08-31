"""独立金标与系统评测质量中心的只读契约。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class GoldQualitySummaryOut(BaseModel):
    total_samples: int
    consensus_samples: int
    adjudicated_samples: int = 0
    gold_samples: int = 0
    evaluation_eligible_samples: int = 0
    pending_adjudication: int
    consensus_coverage: float
    gold_coverage: float = 0
    evaluation_ready: bool
    production_gold_ready: bool
    graph_rag_rollout_ready: bool


class GoldTaskQualityOut(BaseModel):
    task: str
    label: str
    total: int
    consensus: int
    adjudicated: int = 0
    final: int = 0
    evaluation_eligible: int = 0
    pending: int
    coverage: float
    core_fields: list[str]
    file: str


class GoldAgreementOut(BaseModel):
    task: str
    field: str
    n: int
    agreement: float
    cohen_kappa: float | None


class GoldQualityGateOut(BaseModel):
    code: str
    label: str
    status: Literal["passed", "warning", "blocked"]
    current: bool | int | float | None = None
    target: bool | int | float | None = None
    message: str


class GoldFileOut(BaseModel):
    path: str
    rows: int
    sha256: str


class GoldQualityReportOut(BaseModel):
    schema_version: str
    gold_version: str
    gold_state: Literal["consensus", "final"]
    created_at: str
    source_package: str
    summary: GoldQualitySummaryOut
    tasks: list[GoldTaskQualityOut]
    agreement: list[GoldAgreementOut]
    gates: list[GoldQualityGateOut]
    quality_exceptions: list[dict[str, str]] = Field(default_factory=list)
    files: list[GoldFileOut]
    review_artifacts: dict[str, Any]
    source_sha256: dict[str, str]
    system_benchmarks: dict[str, Any] = Field(default_factory=dict)
