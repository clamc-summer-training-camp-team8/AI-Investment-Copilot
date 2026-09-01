"""指标字典与企业指标中心 API 契约。"""

from pydantic import BaseModel, Field


class MetricOut(BaseModel):
    metric_id: str
    version: str
    name: str
    unit: str
    category: str | None = None
    definition: str | None = None
    frequency: str | None = None
    period_type: str
    source_id: str | None = None
    expected_direction: str | None = None
    status: str


class MetricPointOut(BaseModel):
    period: str
    date: str
    value: str


class CompanyMetricOut(BaseModel):
    metric_id: str
    name: str
    category: str
    unit: str
    frequency: str
    definition: str
    source_id: str
    latest_value: str
    latest_period: str
    latest_date: str
    previous_value: str | None = None
    change_value: str | None = None
    change_rate: str | None = None
    observations: list[MetricPointOut] = Field(default_factory=list)


class CompanyMetricCenterOut(BaseModel):
    security_id: str
    updated_at: str | None = None
    metrics: list[CompanyMetricOut] = Field(default_factory=list)


class CompanyMetricRefreshOut(BaseModel):
    security_id: str
    fetched: int
    inserted: int
    errors: list[str] = Field(default_factory=list)
