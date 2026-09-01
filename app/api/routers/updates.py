"""跨覆盖范围的研究动态流。

与雷达页不同，本接口不要求调用方先选定一条投资逻辑；它只返回当前研究员
有权限看到的证据关联，供工作台的“全部动态”使用。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import ActorDep, UowDep
from app.api.feed_presenter import aggregate_feed_items, apply_daily_logic_digests, to_feed_item
from app.core.domain import ThesisQuery
from app.core.enums import ConfirmationStatus, ImpactDirection
from app.core.timeutil import business_date, now
from app.schemas.thesis import (
    EvidenceFeedPage,
    LogicChangeCausalPathOut,
    LogicChangeDigestDetailOut,
    LogicChangeHypothesisImpactOut,
    LogicChangeSourceDocumentOut,
    LogicChangeSourceFactOut,
    PageMeta,
    TodayCompanyUpdateOut,
    TodayCompanyUpdatePage,
)
from app.services import query as query_service
from app.services.permission import can_view_thesis

router = APIRouter(prefix="/updates", tags=["updates"])


@router.get("/today", response_model=TodayCompanyUpdatePage)
def list_today_company_updates(actor: ActorDep, uow: UowDep) -> TodayCompanyUpdatePage:
    """Show today's newly ingested, company-relevant source material by company.

    This intentionally precedes evidence mapping: researchers should see new
    source material immediately, while the RAG relation is still being formed.
    """

    as_of = now()
    start = as_of.replace(hour=0, minute=0, second=0, microsecond=0)
    grouped: dict[str, list] = {}
    for document in uow.documents.list_recent(ingested_from=start, limit=300):
        if not document.security_id or not _document_mentions_assigned_security(document, uow):
            continue
        grouped.setdefault(document.security_id, []).append(document)

    items: list[TodayCompanyUpdateOut] = []
    for security_id, documents in grouped.items():
        security = uow.securities.get(security_id)
        if security is None:
            continue
        latest = max(document.ingested_at or document.published_at for document in documents)
        titles = list(
            dict.fromkeys(
                (document.title or "未命名资料").removeprefix("标题：").strip()
                for document in documents
            )
        )
        items.append(
            TodayCompanyUpdateOut(
                security_id=security_id,
                security_name=security.name,
                document_count=len(documents),
                latest_ingested_at=latest,
                titles=titles[:3],
            )
        )
    return TodayCompanyUpdatePage(
        items=sorted(items, key=lambda item: item.latest_ingested_at, reverse=True), as_of=as_of
    )


@router.get("/logic-changes/{security_id}/{thesis_id}", response_model=LogicChangeDigestDetailOut)
def get_logic_change_detail(
    security_id: str,
    thesis_id: str,
    actor: ActorDep,
    uow: UowDep,
    business_day: Annotated[date | None, Query()] = None,
) -> LogicChangeDigestDetailOut:
    """读取一条日归并变化及其可回查的资料—事实—假设链路。"""
    thesis = uow.thesis.get(thesis_id)
    if thesis is None or thesis.security_id != security_id:
        raise HTTPException(status_code=404, detail="主投资逻辑不存在或不属于该公司")
    if not can_view_thesis(
        actor, owner=thesis.owner, visibility=thesis.visibility, team=thesis.team
    ):
        raise HTTPException(status_code=404, detail="主投资逻辑不存在或无查看权限")
    as_of = business_day or now().date()
    digest = uow.logic_change_digests.get_for_scope(
        security_id=security_id, thesis_id=thesis_id, business_date=as_of
    )
    if digest is None:
        raise HTTPException(status_code=404, detail="该业务日尚未生成归并影响")
    security = uow.securities.get(security_id)
    hypotheses = {item.hypothesis_id: item for item in uow.thesis.list_hypotheses(thesis_id)}
    records = [
        item
        for item in uow.evidence.list_for_thesis(thesis_id)
        if item.security_id == security_id
        and item.ingested_at is not None
        and business_date(item.ingested_at) == as_of
    ]
    source_documents = _source_documents(records, uow, set(digest.citations))
    impacts = []
    for item in digest.hypothesis_impacts:
        hypothesis_id = str(item["hypothesis_id"])
        related_metrics = []
        for metric_id in item.get("related_metric_ids", []):
            mapping = next(
                (
                    value
                    for value in uow.thesis.list_mappings(hypothesis_id)
                    if value.metric_id == str(metric_id)
                ),
                None,
            )
            if mapping is None:
                continue
            definition = uow.metrics.get(mapping.metric_id, mapping.metric_version)
            related_metrics.append(definition.name if definition else mapping.metric_id)
        impacts.append(
            LogicChangeHypothesisImpactOut(
                hypothesis_id=hypothesis_id,
                statement=(
                    hypotheses[hypothesis_id].statement
                    if hypothesis_id in hypotheses
                    else "关联假设"
                ),
                direction=str(item.get("direction") or "待观察"),
                strength=str(item.get("strength")) if item.get("strength") else None,
                strength_reason=(
                    str(item.get("strength_reason")) if item.get("strength_reason") else None
                ),
                rationale=str(item.get("rationale") or "待研究员核验。"),
                business_impact=(
                    str(item.get("business_impact")) if item.get("business_impact") else None
                ),
                indicator_outlook=(
                    str(item.get("indicator_outlook")) if item.get("indicator_outlook") else None
                ),
                impact_layer=(str(item.get("impact_layer")) if item.get("impact_layer") else None),
                directness=str(item.get("directness")) if item.get("directness") else None,
                transmission_status=(
                    str(item.get("transmission_status"))
                    if item.get("transmission_status")
                    else None
                ),
                hypothesis_effect=(
                    str(item.get("hypothesis_effect")) if item.get("hypothesis_effect") else None
                ),
                presentation=str(item.get("presentation")) if item.get("presentation") else None,
                paths=[
                    LogicChangeCausalPathOut(
                        direction=str(path.get("direction") or "中性"),
                        label=str(path.get("label") or "待核验传导路径"),
                        mechanism=str(path.get("mechanism") or "尚未形成可解释传导。"),
                        evidence_ids=[str(value) for value in path.get("evidence_ids", [])],
                    )
                    for path in item.get("paths", [])
                    if isinstance(path, dict)
                ],
                related_metrics=list(dict.fromkeys(related_metrics)),
                evidence_ids=[str(value) for value in item.get("evidence_ids", [])],
            )
        )
    return LogicChangeDigestDetailOut(
        digest_id=digest.digest_id,
        security_id=security_id,
        security_name=security.name if security else security_id,
        thesis_id=thesis_id,
        thesis_title=thesis.title,
        thesis_core_view=thesis.core_view,
        business_date=as_of,
        overall_direction=digest.overall_direction,
        summary=digest.summary,
        confirmation_status=digest.confirmation_status.value,
        candidate_count=digest.candidate_count,
        source_document_count=len(source_documents),
        confidence=digest.confidence,
        open_questions=digest.open_questions,
        model_version=digest.model_version,
        prompt_version=digest.prompt_version,
        hypothesis_impacts=impacts,
        source_documents=source_documents,
    )


@router.get("", response_model=EvidenceFeedPage)
def list_research_updates(
    actor: ActorDep,
    uow: UowDep,
    status: Annotated[list[str] | None, Query()] = None,
    direction: Annotated[str | None, Query()] = None,
    priority: Annotated[list[str] | None, Query()] = None,
    recent_days: Annotated[
        int | None,
        Query(ge=1, le=90, description="仅展示最近 N 天的实时主题；省略时查询全部历史"),
    ] = None,
    business_day: Annotated[
        date | None,
        Query(description="按指定业务日读取已归并的历史逻辑变化，仅用于回溯展示"),
    ] = None,
    today_only: Annotated[
        bool, Query(description="仅展示本业务日新入库资料形成的主题影响")
    ] = False,
    limit: Annotated[int, Query(ge=1, le=query_service.MAX_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EvidenceFeedPage:
    """返回跨公司、按优先级和披露时间排序的可读动态。"""
    try:
        statuses = tuple(ConfirmationStatus(item) for item in (status or []))
        parsed_direction = ImpactDirection(direction) if direction else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="状态或方向筛选值不合法") from exc
    priorities = tuple(priority or ())
    if any(item not in {"high", "medium", "low"} for item in priorities):
        raise HTTPException(status_code=422, detail="优先级必须是 high、medium 或 low")
    if business_day is not None and today_only:
        raise HTTPException(status_code=422, detail="business_day 与 today_only 不能同时使用")

    # 覆盖公司的现行主逻辑以季度观察（observation）形式维护。
    # 动态流必须与工作台读取同一份「现行逻辑全集」，不能只检索 canonical，
    # 否则新闻已经完成解析和关联，却会在跨公司动态页被静默遗漏。
    theses, _ = uow.thesis.search(
        ThesisQuery(limit=query_service.MAX_LIMIT, include_snapshots=True)
    )
    visible_ids = tuple(
        item.thesis_id
        for item in theses
        if can_view_thesis(actor, owner=item.owner, visibility=item.visibility, team=item.team)
    )
    # 先在受控的扫描上限内读取，再过滤供应商的错配资料并进行同源聚合。
    # 若直接以页面 limit 查询，排在前面的无关旧记录会占满窗口，导致后面的
    # 有效候选永远到不了页面。
    records, _ = uow.feed.search(
        thesis_ids=visible_ids,
        statuses=statuses,
        direction=parsed_direction,
        priorities=priorities,
        limit=2_000,
        offset=0,
    )
    # The provider occasionally returns broad-market material even for a
    # stock-code request.  Keep such legacy records out of the reviewer feed
    # unless the archived original itself names the routed company.  Other
    # source types remain unaffected.
    cutoff = (now() - timedelta(days=recent_days)).date() if recent_days else None
    records = [
        item
        for item in records
        if (
            (business_day is not None and _is_ingested_on_business_date(item, uow, business_day))
            or (today_only and _is_ingested_on_business_date(item, uow, now().date()))
            or (business_day is None and not today_only and (cutoff is None or item.disclosed_at.date() >= cutoff))
        )
        and _is_displayable_provider_record(item, uow)
    ]
    cards = aggregate_feed_items(
        [to_feed_item(item, actor_id=actor.user_id) for item in records],
        daily=today_only or business_day is not None,
    )
    if business_day is not None:
        digests = {
            (digest.security_id, digest.thesis_id): digest
            for digest in uow.logic_change_digests.list_for_business_day(
                business_date=business_day
            )
        }
        # 历史回溯只呈现当时已完成归并的公司级卡片，避免混入旧的原子候选。
        cards = [
            card for card in cards if (card.security_id, card.thesis_id) in digests
        ]
        cards = apply_daily_logic_digests(cards, digests)
    elif today_only:
        digest_business_day = business_day or now().date()
        digests = {
            (card.security_id, card.thesis_id): digest
            for card in cards
            if (
                digest := uow.logic_change_digests.get_for_scope(
                    security_id=card.security_id,
                    thesis_id=card.thesis_id,
                    business_date=digest_business_day,
                )
            )
            is not None
        }
        cards = apply_daily_logic_digests(cards, digests)
    total = len(cards)
    return EvidenceFeedPage(
        items=cards[offset : offset + limit],
        page=PageMeta(total=total, limit=limit, offset=offset),
    )


def _is_displayable_provider_record(record, uow) -> bool:
    document = uow.documents.get(record.source_document_id) if record.source_document_id else None
    is_investoday = (
        document is not None and (document.source_id or "").startswith("SRC-INVESTODAY-")
    ) or "data-api.investoday.net/" in (record.source_url or "")
    if not is_investoday:
        return True
    security = uow.securities.get(record.security_id)
    if security is None:
        return False
    text = "\n".join(
        value
        for value in (
            document.title if document else None,
            document.body if document else None,
            record.fact_excerpt,
        )
        if value
    ).lower()
    terms = [security.name, security.ticker or "", security.security_id, *security.aliases]
    return any(str(term).lower() in text for term in terms if str(term).strip())


def _source_documents(records, uow, key_citations: set[str]) -> list[LogicChangeSourceDocumentOut]:
    """按文档归并候选事实；同一事实的多假设关系合并展示，避免重复材料卡片。"""
    grouped: dict[str, dict[str, object]] = {}
    for item in records:
        document_id = item.source_document_id or item.evidence_id
        document = uow.documents.get(item.source_document_id) if item.source_document_id else None
        entry = grouped.setdefault(
            document_id,
            {
                "document_id": document_id,
                "title": item.source_document_title or document_id,
                "doc_type": _source_material_type(
                    document.doc_type if document else None,
                    item.source_url,
                    item.source_document_title,
                ),
                "published_at": document.published_at if document else item.disclosed_at,
                "source_url": item.source_url,
                "facts": {},
            },
        )
        facts = entry["facts"]
        assert isinstance(facts, dict)
        fact = facts.setdefault(
            item.evidence_id,
            {
                "evidence_id": item.evidence_id,
                "fact_excerpt": item.fact_excerpt or "事实摘录待补充",
                "evidence_locator": item.evidence_locator,
                "hypothesis_ids": [],
                "directions": [],
                "is_key_citation": item.evidence_id in key_citations,
            },
        )
        assert isinstance(fact, dict)
        hypothesis_ids = fact["hypothesis_ids"]
        directions = fact["directions"]
        assert isinstance(hypothesis_ids, list) and isinstance(directions, list)
        if item.hypothesis_id not in hypothesis_ids:
            hypothesis_ids.append(item.hypothesis_id)
        if item.direction.value not in directions:
            directions.append(item.direction.value)
        fact["is_key_citation"] = bool(fact["is_key_citation"]) or item.evidence_id in key_citations

    documents = [
        LogicChangeSourceDocumentOut(
            document_id=str(entry["document_id"]),
            title=str(entry["title"]),
            doc_type=str(entry["doc_type"]) if entry["doc_type"] else None,
            published_at=entry["published_at"]
            if isinstance(entry["published_at"], datetime)
            else None,
            source_url=str(entry["source_url"]) if entry["source_url"] else None,
            facts=[LogicChangeSourceFactOut(**fact) for fact in entry["facts"].values()],
        )
        for entry in grouped.values()
    ]
    return sorted(
        documents,
        key=lambda item: (
            not any(fact.is_key_citation for fact in item.facts),
            item.published_at or now(),
        ),
        reverse=False,
    )


def _source_material_type(doc_type: str | None, source_url: str | None, title: str | None) -> str:
    """给历史未分类材料补充仅用于界面的可读类型，不回写原文元数据。"""
    if doc_type and doc_type.strip():
        return doc_type.strip()
    normalized_url = (source_url or "").lower()
    normalized_title = (title or "").lower()
    if "/news" in normalized_url or "新闻" in normalized_title:
        return "新闻"
    if "公告" in normalized_title or "notice" in normalized_url:
        return "公告"
    if "研报" in normalized_title or "research" in normalized_url:
        return "研报"
    return "公开资料"


def _document_mentions_assigned_security(document, uow) -> bool:
    security = uow.securities.get(document.security_id)
    if security is None:
        return False
    text = "\n".join(value for value in (document.title, document.body) if value).lower()
    terms = [security.name, security.ticker or "", security.security_id, *security.aliases]
    return any(str(term).lower() in text for term in terms if str(term).strip())


def _is_ingested_on_business_date(record, uow, target_date) -> bool:
    """Daily work queues follow the date material entered the system, not its publication date."""

    document = uow.documents.get(record.source_document_id) if record.source_document_id else None
    timestamp = (document.ingested_at if document else None) or record.disclosed_at
    return business_date(timestamp) == target_date
