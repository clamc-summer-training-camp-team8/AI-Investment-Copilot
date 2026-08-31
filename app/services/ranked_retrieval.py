from __future__ import annotations

from app.ai.embeddings import embed_text
from app.core.config import Settings
from app.core.domain import UnitOfWork
from app.ranking.profiles import get_profile
from app.ranking.scorer import rank_candidates
from app.ranking.types import RankedCandidate, RankingQuery
from app.services.errors import ValidationFailed
from app.services.permission import Actor


def search(
    uow: UnitOfWork,
    *,
    query: RankingQuery,
    actor: Actor,
    settings: Settings,
) -> tuple[str | None, list[RankedCandidate]]:
    text = query.text.strip()
    if not text:
        raise ValidationFailed("检索词不能为空")
    if not settings.embedding_version:
        raise ValidationFailed("未配置 EMBEDDING_VERSION，排序检索不可用")
    if not query.security_ids:
        raise ValidationFailed("排序先验检索第一版要求指定 security_ids")
    profile = get_profile(query.profile)
    # 扩大候选集后再应用业务先验；先验不能充当硬召回条件。
    candidate_limit = min(max(50, query.top_k * 10), 100)
    hits = uow.assets.hybrid_search_segments(
        query=text,
        query_embedding=embed_text(text, version=settings.embedding_version),
        embedding_version=settings.embedding_version,
        visibility_labels=tuple(sorted(actor.document_labels)),
        security_ids=query.security_ids,
        industries=query.industries,
        published_from=None,
        published_to=query.as_of,
        keyword_weight=profile.keyword_weight,
        vector_weight=profile.vector_weight,
        limit=candidate_limit,
    )
    snapshot = uow.ranking.active_snapshot(
        security_id=query.security_ids[0],
        direction=query.direction,
        horizon=query.horizon,
        as_of=query.as_of,
    )
    priors = {}
    if snapshot:
        rows = uow.ranking.items_for_objects(
            snapshot.snapshot_id,
            object_type="document_segment",
            object_ids=tuple(hit.locator for hit in hits),
        )
        priors = {row.object_id: row for row in rows}
    ranked = rank_candidates(
        hits, priors=priors, profile=profile, top_k=query.top_k, query_text=text
    )
    return (snapshot.snapshot_id if snapshot else None), ranked
