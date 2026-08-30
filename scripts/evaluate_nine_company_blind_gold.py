"""Evaluate ranked retrieval on independently phrased nine-company queries."""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.ai.embeddings import embed_text
from app.core.config import settings
from app.db.models.core import Document, DocumentSegment, Evidence
from app.db.session import session_scope
from app.ranking.profiles import get_profile
from app.ranking.scorer import rank_candidates
from app.ranking.types import RankingQuery
from app.services import ranked_retrieval
from app.services.permission import Actor
from app.services.uow import uow_scope


def _canonical_title(value: str) -> str:
    """Normalize a legacy Windows-import replacement for the em dash."""
    return re.sub(r"\ufffd+", "—", value).strip()


def _metrics(document_ids: list[str], expected: set[str], k: int) -> dict[str, float]:
    # Several segments and legacy copies may represent the same labelled source.
    # This gold labels a relevant source family, so one matching document is a hit.
    unique_ids = list(dict.fromkeys(document_ids))[:k]
    ranks = [index for index, value in enumerate(unique_ids, 1) if value in expected]
    recall = 1.0 if ranks else 0.0
    mrr = 1 / ranks[0] if ranks else 0.0
    ndcg = 1 / math.log2(ranks[0] + 1) if ranks else 0.0
    return {"recall_at_k": recall, "mrr": mrr, "ndcg_at_k": ndcg}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--gold",
        type=Path,
        default=Path("analytics/evaluation/nine_company_blind_retrieval_gold_v1.json"),
    )
    parser.add_argument("--as-of", default="2026-08-24T23:59:59+08:00")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    as_of = datetime.fromisoformat(args.as_of)
    if as_of.tzinfo is None:
        parser.error("--as-of 必须包含时区")
    gold = json.loads(args.gold.read_text(encoding="utf-8"))
    titles = {title for case in gold["cases"] for title in case["expected_document_titles"]}
    with session_scope() as session:
        title_to_ids: dict[str, set[str]] = {}
        document_meta = {}
        evidence_sources = session.execute(
            select(Evidence.source_document_title, Evidence.source_document_id).where(
                Evidence.source_document_title.is_not(None),
                Evidence.source_document_id.is_not(None),
            )
        ).all()
        for title, document_id in evidence_sources:
            title_to_ids.setdefault(_canonical_title(str(title)), set()).add(str(document_id))
        docs = session.scalars(
            select(Document).where(
                Document.document_id.in_(
                    {doc_id for ids in title_to_ids.values() for doc_id in ids}
                )
            )
        ).all()
        for doc in docs:
            document_meta[doc.document_id] = {"title": doc.title, "published_at": doc.published_at}
        valid_locators = set(
            session.execute(select(DocumentSegment.document_id, DocumentSegment.locator)).all()
        )
    actor = Actor(user_id="nine-company-blind-gold", document_labels=frozenset({"公开", "内部"}))
    profile = get_profile("primary_context")
    rows = []
    with uow_scope() as uow:
        for case in gold["cases"]:
            expected = set().union(
                *(
                    title_to_ids.get(_canonical_title(title), set())
                    for title in case["expected_document_titles"]
                )
            )
            snapshot_id, ranked = ranked_retrieval.search(
                uow,
                query=RankingQuery(
                    text=case["query"],
                    security_ids=(case["security_id"],),
                    as_of=as_of,
                    profile="primary_context",
                    top_k=args.top_k,
                ),
                actor=actor,
                settings=settings,
            )
            hits = uow.assets.hybrid_search_segments(
                query=case["query"],
                query_embedding=embed_text(case["query"], version=settings.embedding_version or ""),
                embedding_version=settings.embedding_version or "",
                visibility_labels=tuple(sorted(actor.document_labels)),
                security_ids=(case["security_id"],),
                industries=(),
                published_from=None,
                published_to=as_of,
                keyword_weight=profile.keyword_weight,
                vector_weight=profile.vector_weight,
                limit=max(args.top_k * 5, 25),
            )
            baseline = rank_candidates(
                hits, priors={}, profile=profile, top_k=args.top_k, query_text=case["query"]
            )
            ranked_ids = [item.document_id for item in ranked]
            baseline_ids = [item.document_id for item in baseline]
            future = [
                doc_id
                for doc_id in ranked_ids
                if document_meta.get(doc_id, {}).get("published_at")
                and document_meta[doc_id]["published_at"] > as_of
            ]
            invalid_citations = [
                item.locator
                for item in ranked
                if (item.document_id, item.locator) not in valid_locators
            ]
            rows.append(
                {
                    **case,
                    "expected_document_ids": sorted(expected),
                    "snapshot_id": snapshot_id,
                    "prior": _metrics(ranked_ids, expected, args.top_k),
                    "baseline": _metrics(baseline_ids, expected, args.top_k),
                    "future_leakage_count": len(future),
                    "invalid_citation_count": len(invalid_citations),
                    "returned_document_ids": ranked_ids,
                }
            )

    def avg(path: str) -> float:
        return round(
            sum(row[path.split(".")[0]][path.split(".")[1]] for row in rows) / len(rows), 4
        )

    summary = {
        "cases": len(rows),
        "top_k": args.top_k,
        "prior": {key: avg(f"prior.{key}") for key in ("recall_at_k", "mrr", "ndcg_at_k")},
        "baseline": {key: avg(f"baseline.{key}") for key in ("recall_at_k", "mrr", "ndcg_at_k")},
        "future_leakage_count": sum(row["future_leakage_count"] for row in rows),
        "invalid_citation_count": sum(row["invalid_citation_count"] for row in rows),
        "missing_gold_titles": sorted(
            title for title in titles if _canonical_title(title) not in title_to_ids
        ),
    }
    summary["gate"] = {
        "status": "production_gate_with_product_owner_accepted_human_gold",
        "minimum_recall_at_k": 0.8,
        "passed": summary["future_leakage_count"] == 0
        and summary["invalid_citation_count"] == 0
        and not summary["missing_gold_titles"]
        and summary["prior"]["recall_at_k"] >= 0.8
        and summary["prior"]["ndcg_at_k"] >= summary["baseline"]["ndcg_at_k"],
    }
    report = {
        "gold_version": gold["version"],
        "annotation_status": gold["annotation_status"],
        "as_of": as_of.isoformat(),
        "summary": summary,
        "results": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
