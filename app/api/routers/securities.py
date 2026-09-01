"""证券主数据查询与建档路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import ActorDep, UowDep
from app.core.domain import SecurityRecord
from app.schemas.metric import CompanyMetricCenterOut, CompanyMetricRefreshOut
from app.schemas.security import SecurityIn, SecurityLookupOut, SecurityOut
from app.services import security as security_service
from app.services.company_metric_center import metric_center, refresh_security_metrics
from app.services.errors import ValidationFailed
from app.services.market_security import lookup as lookup_market_security
from app.services.permission import Actor

router = APIRouter(prefix="/securities", tags=["securities"])


def _out(record) -> SecurityOut:
    return SecurityOut(
        security_id=record.security_id,
        name=record.name,
        ticker=record.ticker,
        industry=record.industry,
        aliases=record.aliases,
    )


def _require_local_admin(actor: Actor) -> None:
    # MVP 尚无独立 RBAC 表；本地代理固定注入这个账号。生产上线
    # 前应替换为组织目录中的 security_master:write 权限。
    if actor.user_id != "analyst-mvp" and "security-admin" not in actor.teams:
        raise HTTPException(status_code=403, detail="当前账户无证券主数据建档权限")


@router.get("", response_model=list[SecurityOut])
def list_securities(
    actor: ActorDep,
    uow: UowDep,
    keyword: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[SecurityOut]:
    del actor
    return [_out(record) for record in uow.securities.search(keyword, limit=limit)]


@router.get("/resolve", response_model=list[SecurityLookupOut])
def resolve_security(
    actor: ActorDep,
    uow: UowDep,
    query: Annotated[str, Query(min_length=1, max_length=100)],
) -> list[SecurityLookupOut]:
    """市场全状态表优先；未命中时实时查询并回写市场表。"""
    del actor
    market = uow.securities.search_market(query, limit=8)
    if market:
        return [SecurityLookupOut(**_out(record).model_dump(), source="market_database") for record in market]
    resolved = [
        SecurityLookupOut(
            security_id=item.security_id,
            name=item.name,
            ticker=item.ticker,
            industry=item.industry,
            aliases=[],
            source="market",
        )
        for item in lookup_market_security(query)
    ]
    for item in resolved:
        uow.securities.upsert_market(
            SecurityRecord(
                security_id=item.security_id,
                name=item.name,
                ticker=item.ticker,
                industry=item.industry,
                aliases=item.aliases,
            )
        )
    return resolved


@router.get("/{security_id}", response_model=SecurityOut)
def get_security(security_id: str, actor: ActorDep, uow: UowDep) -> SecurityOut:
    """返回公司研究页所需的证券主数据。"""
    del actor
    record = uow.securities.get(security_id.strip().upper())
    if record is None:
        raise HTTPException(status_code=404, detail="证券不存在")
    return _out(record)


@router.get("/{security_id}/metric-center", response_model=CompanyMetricCenterOut)
def get_metric_center(security_id: str, actor: ActorDep, uow: UowDep) -> CompanyMetricCenterOut:
    del actor
    record = uow.securities.get(security_id.strip().upper())
    if record is None:
        raise HTTPException(status_code=404, detail="证券不存在")
    metrics = metric_center(uow, record.security_id)
    updated_at = max((item["latest_date"] for item in metrics), default=None)
    return CompanyMetricCenterOut(security_id=record.security_id, updated_at=updated_at, metrics=metrics)


@router.post("/{security_id}/metric-center/refresh", response_model=CompanyMetricRefreshOut)
def refresh_metric_center(security_id: str, actor: ActorDep, uow: UowDep) -> CompanyMetricRefreshOut:
    _require_local_admin(actor)
    try:
        return CompanyMetricRefreshOut(**refresh_security_metrics(uow, security_id.strip().upper()))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("", response_model=SecurityOut, status_code=201)
def create_security(payload: SecurityIn, actor: ActorDep, uow: UowDep) -> SecurityOut:
    _require_local_admin(actor)
    try:
        record = security_service.create(
            uow,
            security_id=payload.security_id,
            name=payload.name,
            ticker=payload.ticker,
            industry=payload.industry,
            aliases=payload.aliases,
            actor=actor,
        )
    except ValidationFailed as exc:
        status_code = 409 if "已建档" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return _out(record)
