"""Export compact, time-bounded inputs for an offline logic-topic semantic review."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.models.core import Evidence, Metric, Security
from app.db.models.ranking import (
    LogicTopic,
    LogicTopicRelation,
    RankingPriorItem,
    RankingPriorSnapshot,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args()
    from datetime import datetime

    as_of = datetime.fromisoformat(args.as_of)
    if as_of.tzinfo is None:
        parser.error("--as-of 必须包含时区")
    from app.db.session import session_scope

    with session_scope() as session:
        topics = session.execute(
            select(LogicTopic, Security.name)
            .join(Security, Security.security_id == LogicTopic.security_id)
            .where(LogicTopic.status == "active")
            .order_by(LogicTopic.security_id, LogicTopic.topic_id)
        ).all()
        rows = []
        for topic, company in topics:
            snapshot = session.scalar(
                select(RankingPriorSnapshot)
                .where(
                    RankingPriorSnapshot.security_id == topic.security_id,
                    RankingPriorSnapshot.direction == topic.direction,
                    RankingPriorSnapshot.horizon == topic.horizon,
                    RankingPriorSnapshot.as_of <= as_of,
                    RankingPriorSnapshot.status.in_(
                        ("provisional", "active", "active_experimental")
                    ),
                )
                .order_by(RankingPriorSnapshot.as_of.desc())
                .limit(1)
            )
            item = (
                session.scalar(
                    select(RankingPriorItem).where(
                        RankingPriorItem.snapshot_id == snapshot.snapshot_id,
                        RankingPriorItem.object_type == "logic_topic",
                        RankingPriorItem.object_id == topic.topic_id,
                    )
                )
                if snapshot
                else None
            )
            relations = session.scalars(
                select(LogicTopicRelation).where(
                    LogicTopicRelation.topic_id == topic.topic_id,
                    LogicTopicRelation.status == "active",
                )
            ).all()
            evidence_ids = [row.object_id for row in relations if row.object_type == "evidence"]
            metric_ids = sorted({row.object_id for row in relations if row.object_type == "metric"})
            evidence_rows = (
                session.scalars(
                    select(Evidence).where(Evidence.evidence_id.in_(evidence_ids))
                ).all()
                if evidence_ids
                else []
            )
            metrics = (
                session.scalars(select(Metric).where(Metric.metric_id.in_(metric_ids))).all()
                if metric_ids
                else []
            )
            evidence_by_direction = {"支持": [], "冲突": [], "中性": []}
            seen_locators = {"支持": set(), "冲突": set(), "中性": set()}
            evidence_rows.sort(
                key=lambda evidence: (
                    bool(evidence.is_direct),
                    len(evidence.fact_excerpt or ""),
                    evidence.disclosed_at or topic.created_at,
                ),
                reverse=True,
            )
            for evidence in evidence_rows:
                direction = (
                    evidence.direction if evidence.direction in evidence_by_direction else "中性"
                )
                if (
                    len(evidence_by_direction[direction]) < 3
                    and evidence.evidence_locator not in seen_locators[direction]
                ):
                    seen_locators[direction].add(evidence.evidence_locator)
                    evidence_by_direction[direction].append(
                        {
                            "evidence_id": evidence.evidence_id,
                            "excerpt": (evidence.fact_excerpt or "")[:500],
                            "locator": evidence.evidence_locator,
                            "disclosed_at": evidence.disclosed_at.isoformat()
                            if evidence.disclosed_at
                            else None,
                        }
                    )
            rows.append(
                {
                    "topic_id": topic.topic_id,
                    "security_id": topic.security_id,
                    "company": company,
                    "name": topic.name,
                    "statement": topic.normalized_statement,
                    "direction": topic.direction,
                    "horizon": topic.horizon,
                    "source_thesis_ids": topic.source_thesis_ids,
                    "existing_rank": item.final_rank if item else None,
                    "existing_score": float(item.final_score) if item else None,
                    "features": dict(item.feature_scores or {}) if item else {},
                    "reason_codes": list(item.reason_codes or []) if item else [],
                    "metrics": [
                        {"metric_id": metric.metric_id, "name": metric.name} for metric in metrics
                    ],
                    "evidence": evidence_by_direction,
                }
            )
    payload = {
        "review_version": "logic-topic-model-review-v1-20260830",
        "as_of": as_of.isoformat(),
        "instructions": "Review topic distinctness, company specificity, causal clarity and whether it may be a primary topic. Cite only supplied locators; do not invent facts.",
        "topics": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output": str(args.output), "topics": len(rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
