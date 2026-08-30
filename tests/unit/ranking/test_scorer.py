from __future__ import annotations

from decimal import Decimal

from app.core.domain import AssetSearchHitRecord, RankingPriorItemRecord
from app.ranking.profiles import get_profile
from app.ranking.scorer import rank_candidates


def _hit(
    locator: str, keyword: float, vector: float, content: str | None = None
) -> AssetSearchHitRecord:
    return AssetSearchHitRecord(
        document_id=locator.split("#")[0],
        locator=locator,
        content=content or locator,
        visibility_label="公开",
        rank=keyword + vector,
        retrieval_mode="hybrid",
        keyword_rank=keyword,
        vector_rank=vector,
    )


def _prior(locator: str, score: str) -> RankingPriorItemRecord:
    return RankingPriorItemRecord(
        snapshot_id="RPS-1",
        object_type="document_segment",
        object_id=locator,
        base_rank=1,
        base_score=Decimal(score),
        final_rank=1,
        final_score=Decimal(score),
        feature_scores={"business_materiality": float(score)},
        reason_codes=["CORE_DRIVER"],
    )


def test_prior_reranks_only_retrieved_candidates() -> None:
    hits = [_hit("DOC-A#p1", 1.0, 1.0), _hit("DOC-B#p1", 0.8, 0.8)]
    ranked = rank_candidates(
        hits,
        priors={"DOC-B#p1": _prior("DOC-B#p1", "1")},
        profile=get_profile("primary_context"),
        top_k=2,
    )
    assert {item.locator for item in ranked} == {"DOC-A#p1", "DOC-B#p1"}
    assert ranked[0].locator == "DOC-B#p1"
    assert ranked[0].prior_score == 1.0


def test_document_search_does_not_allow_prior_to_overrule_strong_relevance() -> None:
    hits = [_hit("DOC-A#p1", 1.0, 1.0), _hit("DOC-B#p1", 0.0, 0.0)]
    ranked = rank_candidates(
        hits,
        priors={"DOC-B#p1": _prior("DOC-B#p1", "1")},
        profile=get_profile("document_search"),
        top_k=2,
    )
    assert [item.locator for item in ranked] == ["DOC-A#p1"]


def test_near_duplicate_disclosures_keep_only_best_representative() -> None:
    hits = [
        _hit("DOC-A#p1", 1.0, 1.0, "2026年1月产销快报"),
        _hit("DOC-B#p1", 0.9, 0.9, "2026年2月产销快报"),
        _hit("DOC-C#p1", 0.8, 0.8, "海外销量增长"),
    ]

    ranked = rank_candidates(hits, priors={}, profile=get_profile("primary_context"), top_k=3)

    assert [item.locator for item in ranked] == ["DOC-A#p1", "DOC-C#p1"]


def test_cjk_literal_signal_distinguishes_explicit_quarter() -> None:
    hits = [
        _hit("DOC-Q1#p1", 0.0, 0.9, "2025年第一季度收入和销量增长"),
        _hit("DOC-Q3#p1", 0.0, 0.9, "2025年第三季度收入和销量增长，比较数已重述"),
    ]

    ranked = rank_candidates(
        hits,
        priors={},
        profile=get_profile("primary_context"),
        top_k=2,
        query_text="2025年第三季度收入销量重述口径",
    )

    assert ranked[0].locator == "DOC-Q3#p1"
