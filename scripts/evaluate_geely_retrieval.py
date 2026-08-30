"""Run repeatable source-hit checks for Geely's prior-aware retrieval."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from app.ai.embeddings import embed_text
from app.core.config import PROJECT_ROOT, settings
from app.ranking.profiles import get_profile
from app.ranking.scorer import rank_candidates
from app.services.permission import Actor
from app.services.uow import uow_scope


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        type=Path,
        default=PROJECT_ROOT / "analytics" / "evaluation" / "geely_retrieval_gold_v1.json",
    )
    parser.add_argument(
        "--as-of", default="2026-08-24T23:59:59+08:00"
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    as_of = datetime.fromisoformat(args.as_of)
    if as_of.tzinfo is None:
        parser.error("--as-of 必须包含时区")
    cases = json.loads(args.cases.read_text(encoding="utf-8"))["cases"]
    actor = Actor(user_id="geely-retrieval-evaluator")
    profile = get_profile("primary_context")

    results = []
    with uow_scope() as uow:
        for case in cases:
            # Staged primary sources do not create DocumentRevision records.
            # Their document IDs are deterministically derived from source URLs
            # by import_staged_official_sources, so reproduce that contract here.
            expected_ids = {
                "DOC-STG-" + hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:24]
                for source_url in case["expected_source_urls"]
            }
            hits = uow.assets.hybrid_search_segments(
                query=case["query"],
                query_embedding=embed_text(case["query"], version=settings.embedding_version or ""),
                embedding_version=settings.embedding_version or "",
                visibility_labels=tuple(sorted(actor.document_labels)),
                security_ids=("00175",),
                industries=(),
                published_from=None,
                published_to=as_of,
                keyword_weight=profile.keyword_weight,
                vector_weight=profile.vector_weight,
                limit=100,
            )
            snapshot = uow.ranking.active_snapshot(
                security_id="00175", direction="看多", horizon="12M", as_of=as_of
            )
            priors = (
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
                priors={row.object_id: row for row in priors},
                profile=profile,
                top_k=args.top_k,
                query_text=case["query"],
            )
            returned_ids = {item.document_id for item in ranked}
            results.append(
                {
                    "case_id": case["case_id"],
                    "query": case["query"],
                    "expected_source_hit": bool(expected_ids & returned_ids),
                    "expected_document_ids": sorted(expected_ids),
                    "top_k": [
                        {
                            "rank": item.rank,
                            "document_id": item.document_id,
                            "locator": item.locator,
                            "keyword_score": item.keyword_score,
                            "vector_score": item.vector_score,
                            "retrieval_score": item.retrieval_score,
                            "prior_score": item.prior_score,
                            "final_score": item.final_score,
                            "reason_codes": list(item.reason_codes),
                            "content_preview": item.content[:180].replace("\n", " "),
                        }
                        for item in ranked
                    ],
                }
            )
    hit_count = sum(row["expected_source_hit"] for row in results)
    report = {
        "security_id": "00175",
        "as_of": as_of.isoformat(),
        "snapshot_id": snapshot.snapshot_id if snapshot else None,
        "top_k": args.top_k,
        "cases": results,
        "source_hit_rate": round(hit_count / len(results), 4) if results else 0.0,
        "gate": {"minimum_source_hit_rate": 0.875, "passed": hit_count / len(results) >= 0.875},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cases": len(results), "source_hit_rate": report["source_hit_rate"], "passed": report["gate"]["passed"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
