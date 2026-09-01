"""行业总览的本地板块与公司覆盖目录路由。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import ActorDep, UowDep
from app.schemas.coverage import (
    CoverageCompanyIn,
    CoverageCompanyOut,
    CoverageCompanyUpdateIn,
    CoverageSectorIn,
    CoverageSectorOut,
    CoverageSectorUpdateIn,
)
from app.services import coverage as coverage_service
from app.services.errors import ValidationFailed
from app.services.permission import Actor

router = APIRouter(prefix="/coverage", tags=["coverage"])


def _require_admin(actor: Actor) -> None:
    if actor.user_id != "analyst-mvp" and "security-admin" not in actor.teams:
        raise HTTPException(status_code=403, detail="当前账户无行业总览维护权限")


def _company_out(record) -> CoverageCompanyOut:
    return CoverageCompanyOut(
        coverage_company_id=record.coverage_company_id,
        sector_id=record.sector_id,
        security_id=record.security_id,
        name=record.name,
        ticker=record.ticker,
        industry=record.industry,
        market=record.market,
        owner=record.owner,
        status=record.status,
        updated_at=record.updated_at,
    )


@router.get("", response_model=list[CoverageSectorOut])
def list_coverage(
    actor: ActorDep, uow: UowDep, query: str | None = None
) -> list[CoverageSectorOut]:
    del actor
    return [
        CoverageSectorOut.model_validate(item)
        for item in coverage_service.list_overview(uow, query=query)
    ]


@router.post("/sectors", response_model=CoverageSectorOut, status_code=201)
def add_sector(payload: CoverageSectorIn, actor: ActorDep, uow: UowDep) -> CoverageSectorOut:
    _require_admin(actor)
    try:
        record = coverage_service.create_sector(
            uow,
            name=payload.name,
            code=payload.code,
            description=payload.description,
            actor=actor,
        )
    except ValidationFailed as exc:
        raise HTTPException(status_code=409 if "已存在" in str(exc) else 400, detail=str(exc)) from exc
    return CoverageSectorOut(
        sector_id=record.sector_id,
        name=record.name,
        code=record.code,
        description=record.description,
        status=record.status,
        companies=[],
    )


@router.patch("/sectors/{sector_id}", response_model=CoverageSectorOut)
def edit_sector(
    sector_id: str,
    payload: CoverageSectorUpdateIn,
    actor: ActorDep,
    uow: UowDep,
) -> CoverageSectorOut:
    _require_admin(actor)
    try:
        record = coverage_service.update_sector(
            uow, sector_id=sector_id, name=payload.name, actor=actor
        )
    except ValidationFailed as exc:
        message = str(exc)
        status_code = 404 if "不存在" in message else 409 if "已存在" in message else 400
        raise HTTPException(status_code=status_code, detail=message) from exc
    return CoverageSectorOut(
        sector_id=record.sector_id,
        name=record.name,
        code=record.code,
        description=record.description,
        status=record.status,
        companies=[],
    )


@router.post("/sectors/{sector_id}/companies", response_model=CoverageCompanyOut, status_code=201)
def add_company(
    sector_id: str,
    payload: CoverageCompanyIn,
    actor: ActorDep,
    uow: UowDep,
) -> CoverageCompanyOut:
    _require_admin(actor)
    try:
        record = coverage_service.create_company(
            uow,
            sector_id=sector_id,
            security_id=payload.security_id,
            name=payload.name,
            ticker=payload.ticker,
            industry=payload.industry,
            market=payload.market,
            owner=payload.owner,
            actor=actor,
        )
    except ValidationFailed as exc:
        message = str(exc)
        status_code = 409 if "已在当前板块" in message else 400
        raise HTTPException(status_code=status_code, detail=message) from exc
    return _company_out(record)


@router.patch("/companies/{coverage_company_id}", response_model=CoverageCompanyOut)
def edit_company(
    coverage_company_id: str,
    payload: CoverageCompanyUpdateIn,
    actor: ActorDep,
    uow: UowDep,
) -> CoverageCompanyOut:
    _require_admin(actor)
    try:
        record = coverage_service.update_company(
            uow,
            coverage_company_id=coverage_company_id,
            status=payload.status,
            owner=payload.owner,
            actor=actor,
        )
    except ValidationFailed as exc:
        raise HTTPException(status_code=404 if "不存在" in str(exc) else 400, detail=str(exc)) from exc
    return _company_out(record)
