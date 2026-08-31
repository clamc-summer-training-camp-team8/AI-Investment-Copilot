"""Offline keyword-vs-hybrid retrieval evaluation on independent gold reasons."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime

from analytics.evaluation.p1_baseline import GOLD, GOLD_VERSION, OUTPUT
from app.core.config import settings
from app.services import assets
from app.services.permission import Actor
from app.services.uow import uow_scope


def _metrics(ranks: list[int | None], *, k: int) -> dict[str, int | float]:
    hits = sum(rank is not None and rank <= k for rank in ranks)
    return {"hits": hits, "n": len(ranks), "recall": round(hits / len(ranks), 4) if ranks else 0.0}


def main() -> None:
    if not settings.embedding_version:
        raise SystemExit("EMBEDDING_VERSION 未配置")
    with GOLD.open(encoding="utf-8-sig") as stream:
        gold = list(csv.DictReader(stream))
    with uow_scope() as uow:
        while assets.embed_pending_assets(
            uow, embedding_version=settings.embedding_version, batch_size=1000
        ):
            pass

    # Exercise the same restricted default role used by the local API.  In
    # particular, this evaluator is not allowed to see 内部受限 or 机密 assets.
    actor = Actor(user_id="offline-evaluator")
    keyword_ranks: list[int | None] = []
    hybrid_ranks: list[int | None] = []
    citations = 0
    leakage = 0
    evaluated = 0
    with uow_scope() as uow:
        for row in gold:
            # The independent annotator's reason is the information need; the
            # source URL identifies the expected citation without using the
            # retrieval implementation's rules or vocabulary.
            expected_document = uow.assets.document_id_by_source_url(row["原文链接"])
            if not expected_document:
                continue
            evaluated += 1
            keyword = assets.search_assets(uow, query=row["判断理由"], actor=actor, limit=10)
            hybrid = assets.hybrid_retrieve(
                uow,
                query=row["判断理由"],
                actor=actor,
                settings=settings,
                security_ids=(row["证券代码"],),
                limit=10,
            )
            keyword_ranks.append(
                next(
                    (
                        index
                        for index, hit in enumerate(keyword, 1)
                        if hit.document_id == expected_document
                    ),
                    None,
                )
            )
            hybrid_ranks.append(
                next(
                    (
                        index
                        for index, hit in enumerate(hybrid, 1)
                        if hit.document_id == expected_document
                    ),
                    None,
                )
            )
            citations += sum(hit.document_id == expected_document for hit in hybrid[:1])
            leakage += sum(hit.visibility_label not in actor.document_labels for hit in hybrid)

    def block(ranks: list[int | None]) -> dict[str, object]:
        reciprocals = [1 / rank if rank else 0 for rank in ranks]
        return {
            "recall_at_1": _metrics(ranks, k=1),
            "recall_at_5": _metrics(ranks, k=5),
            "recall_at_10": _metrics(ranks, k=10),
            "mrr": round(sum(reciprocals) / len(reciprocals), 4) if reciprocals else 0.0,
        }

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "gold_version": GOLD_VERSION,
        "embedding_version": settings.embedding_version,
        "evaluator_document_labels": sorted(actor.document_labels),
        "evaluated_queries": evaluated,
        "keyword": block(keyword_ranks),
        "hybrid": block(hybrid_ranks),
        "top1_citation_correctness": {
            "hits": citations,
            "n": evaluated,
            "value": round(citations / evaluated, 4) if evaluated else None,
        },
        "unauthorized_result_count": leakage,
        "pilot_gate": {
            "no_permission_leakage": leakage == 0,
            "hybrid_not_worse_at_5": _metrics(hybrid_ranks, k=5)["recall"]
            >= _metrics(keyword_ranks, k=5)["recall"],
        },
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "rag_retrieval_eval.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
