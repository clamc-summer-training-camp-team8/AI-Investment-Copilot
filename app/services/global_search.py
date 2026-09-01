"""权限感知的跨对象全局搜索。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from app.core.config import Settings
from app.core.domain import AssetSearchHitRecord, ThesisQuery, UnitOfWork
from app.services import assets, audit
from app.services import query as query_service
from app.services.errors import ValidationFailed
from app.services.permission import Actor, can_view_thesis

SEARCH_TYPES = frozenset({"security", "industry", "thesis", "event", "document"})


@dataclass(frozen=True)
class SearchTarget:
    kind: str
    id: str


@dataclass(frozen=True)
class SearchItem:
    id: str
    title: str
    subtitle: str
    match_kind: str
    target: SearchTarget
    excerpt: str | None = None
    content_status: str | None = None
    content_kind: str | None = None
    retrieval_mode: str | None = None
    published_at: datetime | None = None


@dataclass(frozen=True)
class SearchGroup:
    type: str
    items: list[SearchItem] = field(default_factory=list)


@dataclass(frozen=True)
class GlobalSearchResult:
    query: str
    groups: list[SearchGroup]
    request_id: str


def _match_kind(query: str, values: list[tuple[str, str | None]]) -> str:
    needle = query.casefold()
    for label, value in values:
        if value and needle == value.casefold():
            return label
    for label, value in values:
        if value and value.casefold().startswith(needle):
            return f"{label}_prefix"
    return "contains"


def _visible_thesis_for_security(uow: UnitOfWork, actor: Actor, security_id: str):
    thesis = uow.thesis.get_by_security(security_id)
    if thesis and can_view_thesis(
        actor,
        owner=thesis.owner,
        visibility=thesis.visibility,
        team=thesis.team,
    ):
        return thesis
    return None


def _document_search_item(hit: AssetSearchHitRecord) -> SearchItem:
    # A promoted document deliberately retains its old title-only segment so historical
    # locators keep working.  Label that individual hit as title metadata even though the
    # document now also has complete full-text segments.
    content_status = "标题索引" if hit.content_kind == "title_index" else hit.content_status
    return SearchItem(
        id=hit.locator,
        title=hit.source or hit.document_id,
        subtitle=" · ".join(
            value
            for value in (
                content_status,
                hit.published_at.date().isoformat() if hit.published_at else None,
            )
            if value
        ),
        excerpt=hit.content[:300],
        match_kind="hybrid" if hit.retrieval_mode == "hybrid" else "keyword",
        target=SearchTarget("document_segment", hit.locator),
        content_status=content_status,
        content_kind=hit.content_kind,
        retrieval_mode=hit.retrieval_mode,
        published_at=hit.published_at,
    )


def search(
    uow: UnitOfWork,
    *,
    query: str,
    actor: Actor,
    settings: Settings,
    types: tuple[str, ...],
    limit_per_type: int = 5,
) -> GlobalSearchResult:
    normalized = query.strip()
    if not normalized:
        raise ValidationFailed("检索词不能为空")
    requested = tuple(dict.fromkeys(types or tuple(sorted(SEARCH_TYPES))))
    unknown = set(requested) - SEARCH_TYPES
    if unknown:
        raise ValidationFailed(f"不支持的搜索类型: {', '.join(sorted(unknown))}")
    limit = max(1, min(limit_per_type, 10))
    request_id = f"SEARCH-{uuid4().hex}"
    groups: list[SearchGroup] = []

    securities = uow.securities.search(normalized, limit=max(limit * 3, 20))
    securities.sort(
        key=lambda item: (
            0
            if normalized.casefold()
            in {
                item.security_id.casefold(),
                item.name.casefold(),
                (item.ticker or "").casefold(),
                *(alias.casefold() for alias in item.aliases),
            }
            else 1,
            item.name,
        )
    )

    if "security" in requested:
        items: list[SearchItem] = []
        for security in securities[:limit]:
            thesis = _visible_thesis_for_security(uow, actor, security.security_id)
            target = (
                SearchTarget("thesis", thesis.thesis_id)
                if thesis
                else SearchTarget("security", security.security_id)
            )
            items.append(
                SearchItem(
                    id=security.security_id,
                    title=security.name,
                    subtitle=" · ".join(
                        value
                        for value in (security.industry, security.ticker or security.security_id)
                        if value
                    ),
                    match_kind=_match_kind(
                        normalized,
                        [
                            ("security_id", security.security_id),
                            ("name", security.name),
                            ("ticker", security.ticker),
                            *(("alias", alias) for alias in security.aliases),
                            ("industry", security.industry),
                        ],
                    ),
                    target=target,
                )
            )
        groups.append(SearchGroup("security", items))

    if "industry" in requested:
        industries = sorted(
            {
                security.industry
                for security in securities
                if security.industry and normalized.casefold() in security.industry.casefold()
            }
        )[:limit]
        groups.append(
            SearchGroup(
                "industry",
                [
                    SearchItem(
                        id=industry,
                        title=industry,
                        subtitle="行业覆盖",
                        match_kind="exact"
                        if normalized.casefold() == industry.casefold()
                        else "contains",
                        target=SearchTarget("industry", industry),
                    )
                    for industry in industries
                ],
            )
        )

    if "thesis" in requested:
        page = query_service.list_theses(
            uow,
            actor,
            ThesisQuery(keyword=normalized, limit=max(limit * 3, 20), offset=0),
        )
        thesis_candidates = list(page.items)
        known_thesis_ids = {item.thesis_id for item in thesis_candidates}
        for matched_security in securities:
            matched_thesis = _visible_thesis_for_security(uow, actor, matched_security.security_id)
            if matched_thesis and matched_thesis.thesis_id not in known_thesis_ids:
                thesis_candidates.append(matched_thesis)
                known_thesis_ids.add(matched_thesis.thesis_id)
        thesis_items = []
        for thesis in thesis_candidates[:limit]:
            thesis_security = uow.securities.get(thesis.security_id)
            thesis_items.append(
                SearchItem(
                    id=thesis.thesis_id,
                    title=thesis.title,
                    subtitle=f"{thesis_security.name if thesis_security else thesis.security_id} · {thesis.status.value}",
                    excerpt=thesis.core_view[:240],
                    match_kind=_match_kind(
                        normalized, [("title", thesis.title), ("core_view", thesis.core_view)]
                    ),
                    target=SearchTarget("thesis", thesis.thesis_id),
                )
            )
        groups.append(SearchGroup("thesis", thesis_items))

    if "event" in requested:
        event_items = []
        for event in uow.events.search(
            normalized,
            visibility_labels=tuple(sorted(actor.document_labels)),
            published_to=None,
            limit=limit,
        ):
            event_security = uow.securities.get(event.security_id) if event.security_id else None
            thesis = (
                _visible_thesis_for_security(uow, actor, event.security_id)
                if event.security_id
                else None
            )
            target = (
                SearchTarget("thesis", thesis.thesis_id)
                if thesis
                else SearchTarget("event", event.event_id)
            )
            event_items.append(
                SearchItem(
                    id=event.event_id,
                    title=event.summary[:160],
                    subtitle=f"{event_security.name if event_security else '未绑定公司'} · {event.event_type}",
                    match_kind=_match_kind(
                        normalized, [("event_type", event.event_type), ("summary", event.summary)]
                    ),
                    target=target,
                    published_at=event.disclosure_time,
                )
            )
        groups.append(SearchGroup("event", event_items))

    if "document" in requested:
        try:
            hits = assets.hybrid_retrieve(
                uow,
                query=normalized,
                actor=actor,
                settings=settings,
                limit=limit,
            )
        except ValidationFailed:
            hits = assets.search_assets(uow, query=normalized, actor=actor, limit=limit)
        groups.append(
            SearchGroup(
                "document",
                [_document_search_item(hit) for hit in hits[:limit]],
            )
        )

    audit.record(
        uow.audit,
        actor=actor.user_id,
        action="全局搜索",
        object_type="search_request",
        object_id=request_id,
        detail={
            "query_length": len(normalized),
            "types": list(requested),
            "result_counts": {group.type: len(group.items) for group in groups},
        },
    )
    return GlobalSearchResult(normalized, groups, request_id)
