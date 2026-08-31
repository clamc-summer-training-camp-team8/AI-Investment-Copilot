"""指标字典 API 契约。"""

from pydantic import BaseModel


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
