"""Export a bounded, traceable ranking-review packet for offline model review."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from app.ai.embeddings import embed_text
from app.core.config import settings
from app.db.session import session_scope
from app.ranking.features import score_for_object
from app.ranking.profiles import get_profile
from app.services.permission import Actor
from scripts.build_ranking_priors import _database_inputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--security-id", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--query", help="按实际检索候选导出，而不是按全库规则初排导出")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    as_of = datetime.fromisoformat(args.as_of)
    if as_of.tzinfo is None:
        parser.error("--as-of 必须包含时区")

    with session_scope() as session:
        inputs = _database_inputs(session, security_id=args.security_id, as_of=as_of)
        if args.query:
            from app.db.repositories import build_uow

            profile = get_profile("primary_context")
            actor = Actor(
                user_id="ranking-review-export",
                document_labels=frozenset({"公开", "内部"}),
            )
            hits = build_uow(session).assets.hybrid_search_segments(
                query=args.query,
                query_embedding=embed_text(args.query, version=settings.embedding_version or ""),
                embedding_version=settings.embedding_version or "",
                visibility_labels=tuple(sorted(actor.document_labels)),
                security_ids=(args.security_id,),
                industries=(),
                published_from=None,
                published_to=as_of,
                keyword_weight=profile.keyword_weight,
                vector_weight=profile.vector_weight,
                limit=args.limit,
            )
            input_by_id = {row.object_id: row for row in inputs}
            rows = [input_by_id[hit.locator] for hit in hits if hit.locator in input_by_id]
        else:
            rows = sorted(
                inputs,
                key=lambda row: (-score_for_object(row.object_type, row.features), row.object_id),
            )[: args.limit]
    packet = {
        "security_id": args.security_id,
        "as_of": as_of.isoformat(),
        "object_type": "document_segment",
        "query": args.query,
        "instructions": (
            "仅评价给定条目。主逻辑的经营事实、业绩、销量、价格、产能、产品审批、"
            "可验证指标及重要反证优先；会议通知、制度、法律意见、权益变动和重复材料降权。"
        ),
        "candidates": [
            {
                "object_id": row.object_id,
                "base_score": score_for_object(row.object_type, row.features),
                "feature_scores": row.features.as_dict(),
                "reason_codes": list(row.reason_codes),
                "citation_locators": list(row.citation_locators),
                "content": row.content,
            }
            for row in rows
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output": str(args.output), "candidates": len(rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
