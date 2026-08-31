"""Evaluate prior-aware retrieval against the same candidate set's relevance order."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from app.ai.embeddings import embed_text
from app.core.config import settings
from app.ranking.profiles import get_profile
from app.ranking.scorer import rank_candidates
from app.services.permission import Actor
from app.services.uow import uow_scope

DEFAULT_CASES = (
    ("688981", "先进制程 产能 利用率 盈利质量"),
    ("600276", "创新药 临床 管线 商业化 收入"),
    ("002594", "新能源汽车 销量 毛利率 海外扩张"),
)


def _duplicate_count(contents: list[str]) -> int:
    keys = [re.sub(r"[\W_\d]+", "", value).lower()[:160] for value in contents]
    keys = [value for value in keys if value]
    return len(keys) - len(set(keys))


def _evaluate(
    security_id: str, query_text: str, *, as_of: datetime, top_k: int, candidate_pool: int
) -> dict:
    actor = Actor(user_id="ranking-prior-eval", document_labels=frozenset({"公开", "内部"}))
    profile = get_profile("primary_context")
    with uow_scope() as uow:
        hits = uow.assets.hybrid_search_segments(
            query=query_text,
            query_embedding=embed_text(query_text, version=settings.embedding_version or ""),
            embedding_version=settings.embedding_version or "",
            visibility_labels=tuple(sorted(actor.document_labels)),
            security_ids=(security_id,),
            industries=(),
            published_from=None,
            published_to=as_of,
            keyword_weight=profile.keyword_weight,
            vector_weight=profile.vector_weight,
            limit=candidate_pool,
        )
        snapshot = uow.ranking.active_snapshot(
            security_id=security_id, direction="看多", horizon="12M", as_of=as_of
        )
        prior_rows = (
            uow.ranking.items_for_objects(
                snapshot.snapshot_id,
                object_type="document_segment",
                object_ids=tuple(hit.locator for hit in hits),
            )
            if snapshot
            else []
        )
        ranked = rank_candidates(
            hits,
            priors={row.object_id: row for row in prior_rows},
            profile=profile,
            top_k=top_k,
            query_text=query_text,
        )
    snapshot_id = snapshot.snapshot_id if snapshot else None

    baseline = rank_candidates(
        hits, priors={}, profile=profile, top_k=candidate_pool, query_text=query_text
    )
    relevance_order = {item.locator: item.rank for item in baseline}
    baseline_top = {item.locator for item in baseline[:top_k]}
    ranked_top = {item.locator for item in ranked}
    rows = []
    for item in ranked:
        rows.append(
            {
                "final_rank": item.rank,
                "relevance_rank": relevance_order.get(item.locator, candidate_pool + 1),
                "rank_delta": relevance_order.get(item.locator, candidate_pool + 1) - item.rank,
                "retrieval_score": item.retrieval_score,
                "prior_score": item.prior_score,
                "final_score": item.final_score,
                "locator": item.locator,
                "reason_codes": list(item.reason_codes),
                "content_preview": item.content[:120].replace("\n", " "),
            }
        )
    return {
        "security_id": security_id,
        "query": query_text,
        "snapshot_id": snapshot_id,
        "returned": len(rows),
        "candidate_pool": len(hits),
        "prior_coverage": (
            sum(item.prior_score > 0 for item in ranked) / len(ranked) if ranked else 0.0
        ),
        "changed_positions": sum(row["rank_delta"] != 0 for row in rows),
        "entered_top_k": sorted(ranked_top - baseline_top),
        "exited_top_k": sorted(baseline_top - ranked_top),
        "low_value_top_k": sum("LOW_VALUE_DISCLOSURE" in item.reason_codes for item in ranked),
        "duplicate_top_k": _duplicate_count([item.content for item in ranked]),
        "results": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", default="2026-08-24T23:59:59+08:00")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--candidate-pool", type=int, default=100)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    as_of = datetime.fromisoformat(args.as_of)
    if as_of.tzinfo is None:
        parser.error("--as-of 必须包含时区")

    report = {
        "as_of": as_of.isoformat(),
        "profile": "primary_context",
        "embedding_version": settings.embedding_version,
        "cases": [
            _evaluate(
                security_id,
                text,
                as_of=as_of,
                top_k=args.top_k,
                candidate_pool=args.candidate_pool,
            )
            for security_id, text in DEFAULT_CASES
        ],
    }
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
