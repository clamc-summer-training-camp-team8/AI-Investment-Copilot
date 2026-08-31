"""指标字典查询；MVP 不在研究编辑器中开放无治理新建。"""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ActorDep, UowDep
from app.schemas.metric import MetricOut

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("", response_model=list[MetricOut])
def list_metrics(
    actor: ActorDep,
    uow: UowDep,
    keyword: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[MetricOut]:
    del actor
    return [
        MetricOut(
            metric_id=item.metric_id,
            version=item.version,
            name=item.name,
            unit=item.unit,
            category=item.category,
            definition=item.definition,
            frequency=item.frequency,
            period_type=item.period_type,
            source_id=item.source_id,
            expected_direction=(item.expected_direction.value if item.expected_direction else None),
            status=item.status,
        )
        for item in uow.metrics.search(keyword, limit=limit)
    ]
