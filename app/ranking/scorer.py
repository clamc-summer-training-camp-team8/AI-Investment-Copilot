from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import replace

from app.core.domain import AssetSearchHitRecord, RankingPriorItemRecord
from app.ranking.profiles import RankingProfile
from app.ranking.types import RankedCandidate


def _dedupe_key(content: str) -> str:
    """Collapse mechanically repeated disclosures while retaining one representative."""
    return re.sub(r"[\W_\d]+", "", content).lower()[:160]


def _rank_percentiles(values: Sequence[float]) -> list[float]:
    """按候选集排名映射到 [0, 1]，避免不同检索分数的量纲漂移。"""
    if not values:
        return []
    positive = [index for index, value in enumerate(values) if value > 0]
    if not positive:
        return [0.0] * len(values)
    result = [0.0] * len(values)
    order = sorted(positive, key=lambda index: (-values[index], index))
    position = 0
    while position < len(order):
        end = position + 1
        while end < len(order) and values[order[end]] == values[order[position]]:
            end += 1
        # 同分候选共享同一分位，避免数据库返回顺序成为隐性排序信号。
        percentile = (len(order) - position) / len(order)
        for index in order[position:end]:
            result[index] = percentile
        position = end
    return result


def _cjk_literal_relevance(query: str, content: str) -> float:
    """Provide lexical relevance when DB full-text has no CJK tokenizer."""
    normalized_query = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", query).lower()
    normalized_content = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", content).lower()
    if len(normalized_query) < 2 or len(normalized_content) < 2:
        return 0.0
    query_grams = {
        normalized_query[index : index + 2] for index in range(len(normalized_query) - 1)
    }
    content_grams = {
        normalized_content[index : index + 2] for index in range(len(normalized_content) - 1)
    }
    if not query_grams or not content_grams:
        return 0.0
    return len(query_grams & content_grams) / len(query_grams)


def rank_candidates(
    hits: Sequence[AssetSearchHitRecord],
    *,
    priors: Mapping[str, RankingPriorItemRecord],
    profile: RankingProfile,
    top_k: int,
    query_text: str | None = None,
) -> list[RankedCandidate]:
    keyword = _rank_percentiles(
        [
            max(
                float(item.keyword_rank or 0),
                _cjk_literal_relevance(query_text, item.content) if query_text else 0.0,
            )
            for item in hits
        ]
    )
    vector = _rank_percentiles([max(float(item.vector_rank or 0), 0.0) for item in hits])
    candidates: list[RankedCandidate] = []
    for index, hit in enumerate(hits):
        if (
            profile.minimum_relevance > 0
            and float(hit.keyword_rank or 0) <= 0
            and float(hit.vector_rank or 0) <= 0
        ):
            continue
        relevance_total = profile.keyword_weight + profile.vector_weight
        retrieval = (
            profile.keyword_weight * keyword[index] + profile.vector_weight * vector[index]
        ) / max(relevance_total, 1e-12)
        if retrieval < profile.minimum_relevance:
            continue
        prior = priors.get(hit.locator)
        prior_score = float(prior.final_score) if prior else 0.0
        final = profile.relevance_weight * retrieval + profile.prior_weight * prior_score
        candidates.append(
            RankedCandidate(
                object_id=hit.locator,
                object_type="document_segment",
                document_id=hit.document_id,
                locator=hit.locator,
                content=hit.content,
                visibility_label=hit.visibility_label,
                keyword_score=round(keyword[index], 8),
                vector_score=round(vector[index], 8),
                graph_score=None,
                retrieval_score=round(retrieval, 8),
                prior_score=round(prior_score, 8),
                final_score=round(final, 8),
                rank=0,
                feature_scores=(dict(prior.feature_scores) if prior else {}),
                reason_codes=(tuple(prior.reason_codes) if prior else ()),
                metadata={"retrieval_mode": hit.retrieval_mode},
            )
        )
    candidates.sort(key=lambda item: (-item.final_score, -item.retrieval_score, item.locator))
    unique: list[RankedCandidate] = []
    seen: set[str] = set()
    for item in candidates:
        key = _dedupe_key(item.content)
        if key and key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= top_k:
            break
    return [replace(item, rank=index) for index, item in enumerate(unique, start=1)]
