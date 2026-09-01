"""行业总览的本地板块与公司覆盖目录业务逻辑。"""

from __future__ import annotations

import hashlib
from uuid import uuid4

from app.core.domain import CoverageCompanyRecord, CoverageSectorRecord, ThesisRecord, UnitOfWork
from app.core.enums import ThesisStatus
from app.services import audit
from app.services import security as security_service
from app.services.errors import ValidationFailed
from app.services.permission import Actor


def research_sector(industry: str | None) -> str:
    """把证券主数据的完整行业分类归并成可维护的研究板块。"""
    value = (industry or "").strip()
    if not value:
        return "未分类"
    if "新能源汽车" in value:
        return "新能源汽车"
    if any(item in value for item in ("光伏", "储能", "电力设备", "电气机械")):
        return "新能源与储能"
    if "医药" in value or "医疗" in value:
        return "医药"
    if "半导体" in value or "芯片" in value:
        return "芯片半导体"
    if "汽车" in value:
        return "汽车"
    if any(item in value for item in ("酒", "饮料", "食品", "消费")):
        return "大消费"
    if any(item in value for item in ("软件", "计算机", "通信", "电子设备")):
        return "电子信息"
    return value.split("-", 1)[0].strip() or value


def _market(ticker: str | None) -> str:
    value = (ticker or "").upper()
    if value.endswith(".HK"):
        return "港股"
    if value.endswith((".US", ".NASDAQ", ".NYSE")) or value.isalpha():
        return "美股"
    if value.endswith((".SH", ".SS", ".SZ", ".BJ")) or (value.isdigit() and len(value) == 6):
        return "A股"
    if value.isdigit() and len(value) == 5:
        return "港股"
    return "未标注"


def _require_repo(uow: UnitOfWork):
    if uow.coverage is None:
        raise ValidationFailed("覆盖目录仓储尚未配置，请先执行数据库迁移")
    return uow.coverage


def _sector_id() -> str:
    return f"SEC-{uuid4().hex[:20]}"


def _company_id() -> str:
    return f"COV-{uuid4().hex[:20]}"


def _is_maintained_thesis(thesis: ThesisRecord | None) -> bool:
    """只有研究员已进入维护阶段的真实主逻辑才计入覆盖。"""
    return bool(
        thesis
        and thesis.thesis_kind == "canonical"
        and not thesis.is_illustrative
        and thesis.status
        in {ThesisStatus.VALIDATING, ThesisStatus.DIVERGENT, ThesisStatus.MAJOR_RISK}
    )


def _maintained_theses_by_security(uow: UnitOfWork, security_ids: tuple[str, ...]):
    return {
        security_id: thesis
        for security_id, thesis in uow.thesis.get_by_securities(security_ids).items()
        if _is_maintained_thesis(thesis)
    }


def bootstrap_from_securities(uow: UnitOfWork) -> None:
    """首次打开行业总览时，把已有证券主数据快照到本地覆盖目录。"""
    repo = _require_repo(uow)
    if repo.list_sectors():
        return
    securities = uow.securities.search(limit=5000)
    theses_by_security = _maintained_theses_by_security(
        uow, tuple(item.security_id for item in securities)
    )
    sectors: dict[str, CoverageSectorRecord] = {}
    for security in securities:
        name = research_sector(security.industry)
        sector = sectors.get(name)
        if sector is None:
            sector = CoverageSectorRecord(
                sector_id=_sector_id(),
                name=name,
                code=f"SEC-{len(sectors) + 1:02d}",
                description="研究板块；公司下方显示正式行业分类",
                sort_order=len(sectors),
            )
            sectors[name] = sector
            repo.add_sector(sector)
        if repo.find_company(sector_id=sector.sector_id, security_id=security.security_id):
            continue
        thesis = theses_by_security.get(security.security_id)
        repo.add_company(
            CoverageCompanyRecord(
                coverage_company_id=_company_id(),
                sector_id=sector.sector_id,
                security_id=security.security_id,
                name=security.name,
                ticker=security.ticker,
                industry=security.industry,
                market=_market(security.ticker),
                owner=thesis.owner if thesis else "待分配",
                status="正常覆盖" if thesis else "待建档",
            )
        )


def list_overview(uow: UnitOfWork, *, query: str | None = None) -> list[dict[str, object]]:
    repo = _require_repo(uow)
    # 旧环境可能还没有覆盖目录迁移。行业总览仍可只读展示证券主数据，
    # 但不在首次访问时偷偷创建板块或公司记录。
    if not getattr(repo, "available", True):
        return _read_only_overview(uow, query=query)
    bootstrap_from_securities(uow)
    sectors = repo.list_sectors()
    companies = repo.list_companies()
    theses_by_security = _maintained_theses_by_security(
        uow, tuple(item.security_id for item in companies)
    )
    counts = uow.thesis.counts_for_theses(tuple(item.thesis_id for item in theses_by_security.values()))
    by_sector: dict[str, list[dict[str, object]]] = {sector.sector_id: [] for sector in sectors}
    for company in companies:
        thesis = theses_by_security.get(company.security_id)
        hypothesis_count, mapping_count = counts.get(thesis.thesis_id, (0, 0)) if thesis else (0, 0)
        status = (
            "暂停覆盖"
            if company.status == "暂停覆盖"
            else "正常覆盖" if thesis else "待建档"
        )
        by_sector.setdefault(company.sector_id, []).append(
            {
                "coverage_company_id": company.coverage_company_id,
                "sector_id": company.sector_id,
                "security_id": company.security_id,
                "name": company.name,
                "ticker": company.ticker,
                "industry": company.industry,
                "market": company.market or _market(company.ticker),
                "owner": thesis.owner if thesis else company.owner,
                "status": status,
                "thesis_id": thesis.thesis_id if thesis else None,
                "thesis_title": thesis.title if thesis else None,
                "thesis_status": thesis.status.value if thesis else None,
                "thesis_count": 1 if thesis else 0,
                "hypothesis_count": hypothesis_count,
                "configured_metric_count": mapping_count,
                "updated_at": company.updated_at,
            }
        )
    normalized_query = (query or "").strip().casefold()
    return [
        {
            "sector_id": sector.sector_id,
            "name": sector.name,
            "code": sector.code,
            "description": sector.description or "研究板块；公司下方显示正式行业分类",
            "status": sector.status,
            "companies": by_sector.get(sector.sector_id, []),
        }
        for sector in sectors
        if sector.status == "active"
        and (
            not normalized_query
            or normalized_query
            in " ".join((sector.name, sector.code or "", sector.description or "")).casefold()
        )
    ]


def _read_only_overview(
    uow: UnitOfWork, *, query: str | None = None
) -> list[dict[str, object]]:
    """覆盖目录表不可用时，从证券主数据和 Thesis 组装只读视图。"""
    groups: dict[str, dict[str, object]] = {}
    securities = uow.securities.search(limit=5000)
    theses_by_security = _maintained_theses_by_security(
        uow, tuple(item.security_id for item in securities)
    )
    counts = uow.thesis.counts_for_theses(tuple(item.thesis_id for item in theses_by_security.values()))
    for security in securities:
        sector_name = research_sector(security.industry)
        sector = groups.setdefault(
            sector_name,
            {
                "sector_id": f"MSEC-{hashlib.md5(sector_name.encode('utf-8')).hexdigest()}",
                "name": sector_name,
                "code": None,
                "description": "研究板块；公司下方显示正式行业分类",
                "status": "active",
                "companies": [],
            },
        )
        thesis = theses_by_security.get(security.security_id)
        hypothesis_count, mapping_count = counts.get(thesis.thesis_id, (0, 0)) if thesis else (0, 0)
        sector["companies"].append(
            {
                "coverage_company_id": f"MSEC-COMP-{hashlib.md5(security.security_id.encode('utf-8')).hexdigest()}",
                "sector_id": sector["sector_id"],
                "security_id": security.security_id,
                "name": security.name,
                "ticker": security.ticker,
                "industry": security.industry,
                "market": _market(security.ticker),
                "owner": thesis.owner if thesis else "待分配",
                "status": "正常覆盖" if thesis else "待建档",
                "thesis_id": thesis.thesis_id if thesis else None,
                "thesis_title": thesis.title if thesis else None,
                "thesis_status": thesis.status.value if thesis else None,
                "thesis_count": 1 if thesis else 0,
                "hypothesis_count": hypothesis_count,
                "configured_metric_count": mapping_count,
                "updated_at": thesis.established_on if thesis else None,
            }
        )
    normalized_query = (query or "").strip().casefold()
    return [
        {**sector, "companies": sorted(sector["companies"], key=lambda item: (item["name"], item["security_id"]))}
        for sector in sorted(groups.values(), key=lambda item: item["name"])
        if not normalized_query
        or normalized_query
        in " ".join(
            (str(sector["name"]), str(sector.get("code") or ""), str(sector.get("description") or ""))
        ).casefold()
    ]


def create_sector(
    uow: UnitOfWork,
    *,
    name: str,
    code: str | None,
    description: str | None,
    actor: Actor,
) -> CoverageSectorRecord:
    repo = _require_repo(uow)
    normalized_name = name.strip()
    if not normalized_name:
        raise ValidationFailed("板块名称不能为空")
    if any(item.name == normalized_name for item in repo.list_sectors()):
        raise ValidationFailed(f"板块 {normalized_name} 已存在")
    record = CoverageSectorRecord(
        sector_id=_sector_id(),
        name=normalized_name,
        code=(code or "").strip() or None,
        description=(description or "").strip() or "研究板块；公司下方显示正式行业分类",
        sort_order=len(repo.list_sectors()),
    )
    repo.add_sector(record)
    audit.record(uow.audit, actor=actor.user_id, action="创建研究板块", object_type="coverage_sector", object_id=record.sector_id, detail={"name": record.name})
    return record


def update_sector(
    uow: UnitOfWork,
    *,
    sector_id: str,
    name: str,
    actor: Actor,
) -> CoverageSectorRecord:
    repo = _require_repo(uow)
    record = repo.get_sector(sector_id)
    if record is None:
        raise ValidationFailed("板块不存在")
    normalized_name = name.strip()
    if not normalized_name:
        raise ValidationFailed("板块名称不能为空")
    if any(
        item.sector_id != sector_id and item.name == normalized_name
        for item in repo.list_sectors()
    ):
        raise ValidationFailed(f"板块 {normalized_name} 已存在")
    old_name = record.name
    record.name = normalized_name
    repo.update_sector(record)
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action="修改研究板块",
        object_type="coverage_sector",
        object_id=record.sector_id,
        detail={"old_name": old_name, "name": record.name},
    )
    return record


def create_company(
    uow: UnitOfWork,
    *,
    sector_id: str,
    security_id: str | None,
    name: str | None,
    ticker: str | None,
    industry: str | None,
    market: str | None,
    owner: str | None,
    actor: Actor,
) -> CoverageCompanyRecord:
    repo = _require_repo(uow)
    if repo.get_sector(sector_id) is None:
        raise ValidationFailed("目标板块不存在")
    normalized_id = (security_id or "").strip().upper()
    canonical = uow.securities.get(normalized_id) if normalized_id else None
    if canonical is None:
        market_matches = uow.securities.search_market(normalized_id, limit=1) if normalized_id else []
        if not market_matches and name:
            market_matches = uow.securities.search_market(name.strip(), limit=1)
        source = market_matches[0] if market_matches else None
        if source:
            normalized_id = source.security_id
            canonical = source
        elif not name or not name.strip():
            raise ValidationFailed("未找到证券，请确认代码或名称")
        else:
            canonical = security_service.create(
                uow,
                security_id=normalized_id,
                name=name,
                ticker=ticker,
                industry=industry,
                aliases=[],
                actor=actor,
            )
    if repo.find_company(sector_id=sector_id, security_id=canonical.security_id):
        raise ValidationFailed("该公司已在当前板块中")
    record = CoverageCompanyRecord(
        coverage_company_id=_company_id(),
        sector_id=sector_id,
        security_id=canonical.security_id,
        name=canonical.name,
        ticker=canonical.ticker or ticker,
        industry=canonical.industry or industry,
        market=(market or _market(canonical.ticker)).strip(),
        owner=(owner or "待分配").strip() or "待分配",
        status="待建档",
    )
    repo.add_company(record)
    audit.record(uow.audit, actor=actor.user_id, action="添加覆盖公司", object_type="coverage_company", object_id=record.coverage_company_id, detail={"security_id": record.security_id, "sector_id": sector_id})
    return record


def update_company(
    uow: UnitOfWork,
    *,
    coverage_company_id: str,
    status: str | None,
    owner: str | None,
    actor: Actor,
) -> CoverageCompanyRecord:
    repo = _require_repo(uow)
    record = repo.get_company(coverage_company_id)
    if record is None:
        raise ValidationFailed("覆盖公司不存在")
    if status is not None:
        if status not in {"正常覆盖", "待建档", "暂停覆盖"}:
            raise ValidationFailed("不支持的覆盖状态")
        record.status = status
    if owner is not None:
        record.owner = owner.strip() or "待分配"
    repo.update_company(record)
    audit.record(uow.audit, actor=actor.user_id, action="更新覆盖公司", object_type="coverage_company", object_id=record.coverage_company_id, detail={"status": record.status, "owner": record.owner})
    return record
