"""Nine-company traceability smoke test for prior-aware retrieval.

The cases are sampled from existing candidate evidence, so this is not an
independent relevance benchmark.  It verifies the narrower production contract:
an evidence-backed query must retrieve its traceable source document in Top-K.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.db.models.core import Evidence, Hypothesis, Security
from app.db.session import session_scope
from app.ranking.types import RankingQuery
from app.services import ranked_retrieval
from app.services.permission import Actor
from app.services.uow import uow_scope


def _cases(as_of: datetime, per_company: int) -> list[dict]:
    with session_scope() as session:
        rows = session.execute(
            select(Evidence, Hypothesis, Security)
            .join(Hypothesis, Hypothesis.hypothesis_id == Evidence.hypothesis_id)
            .join(Security, Security.security_id == Evidence.security_id)
            .where(
                Evidence.fact_excerpt.is_not(None),
                ~Evidence.fact_excerpt.like("公告标题：%"),
                Evidence.source_document_id.is_not(None),
                Evidence.disclosed_at <= as_of,
                Security.industry.in_(("芯片半导体", "医药", "新能源汽车")),
            )
            .order_by(Security.security_id, Evidence.disclosed_at.desc(), Evidence.evidence_id)
        ).all()
    grouped: dict[str, dict[str, list[tuple]]] = defaultdict(lambda: defaultdict(list))
    equivalent_documents: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)
    for evidence, hypothesis, security in rows:
        fact_key = (
            security.security_id,
            evidence.direction,
            hypothesis.hypothesis_id,
            str(evidence.fact_excerpt),
        )
        equivalent_documents[fact_key].add(str(evidence.source_document_id))
        existing_keys = {
            (
                item[2].security_id,
                item[0].direction,
                item[1].hypothesis_id,
                str(item[0].fact_excerpt),
            )
            for item in grouped[security.security_id][evidence.direction]
        }
        if fact_key not in existing_keys:
            grouped[security.security_id][evidence.direction].append(
                (evidence, hypothesis, security)
            )
    cases: list[dict] = []
    for security_id in sorted(grouped):
        ordered = []
        # Guarantee both sides of the logic are tested before filling remaining slots.
        for direction in ("支持", "冲突"):
            if grouped[security_id].get(direction):
                ordered.append(grouped[security_id][direction][0])
        remaining = [
            row
            for direction_rows in grouped[security_id].values()
            for row in direction_rows
            if row not in ordered
        ]
        ordered.extend(remaining[: max(0, per_company - len(ordered))])
        for index, (evidence, hypothesis, security) in enumerate(ordered[:per_company], 1):
            excerpt = str(evidence.fact_excerpt)
            fact_key = (
                security_id,
                evidence.direction,
                hypothesis.hypothesis_id,
                excerpt,
            )
            cases.append(
                {
                    "case_id": f"{security_id}-{index:02d}",
                    "security_id": security_id,
                    "company": security.name,
                    "direction": evidence.direction,
                    "hypothesis": hypothesis.name,
                    "query": f"{hypothesis.name} {excerpt[:120]}",
                    "expected_document_ids": sorted(equivalent_documents[fact_key]),
                    "evidence_id": evidence.evidence_id,
                }
            )
    return cases


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", default="2026-08-24T23:59:59+08:00")
    parser.add_argument("--per-company", type=int, default=2)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    as_of = datetime.fromisoformat(args.as_of)
    if as_of.tzinfo is None:
        parser.error("--as-of 必须包含时区")
    cases = _cases(as_of, args.per_company)
    actor = Actor(user_id="nine-company-retrieval-smoke")
    results = []
    with uow_scope() as uow:
        for case in cases:
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
            hit_rank = next(
                (item.rank for item in ranked if item.document_id in case["expected_document_ids"]),
                None,
            )
            results.append(
                {
                    **case,
                    "snapshot_id": snapshot_id,
                    "expected_source_hit": hit_rank is not None,
                    "hit_rank": hit_rank,
                    "returned": [
                        {
                            "rank": item.rank,
                            "document_id": item.document_id,
                            "locator": item.locator,
                            "final_score": item.final_score,
                        }
                        for item in ranked
                    ],
                }
            )
    by_company = {}
    for company in sorted({row["company"] for row in results}):
        company_rows = [row for row in results if row["company"] == company]
        hits = sum(row["expected_source_hit"] for row in company_rows)
        by_company[company] = {
            "cases": len(company_rows),
            "hits": hits,
            "hit_rate": round(hits / len(company_rows), 4),
        }
    hits = sum(row["expected_source_hit"] for row in results)
    rate = round(hits / len(results), 4) if results else 0.0
    report = {
        "evaluation_type": "traceability_smoke_not_independent_relevance_gold",
        "case_scope": "non_title_evidence_facts_only",
        "as_of": as_of.isoformat(),
        "top_k": args.top_k,
        "cases": len(results),
        "hits": hits,
        "hit_rate": rate,
        "gate": {"minimum_hit_rate": 0.9, "passed": rate >= 0.9},
        "by_company": by_company,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {key: report[key] for key in ("cases", "hits", "hit_rate", "gate", "by_company")},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
