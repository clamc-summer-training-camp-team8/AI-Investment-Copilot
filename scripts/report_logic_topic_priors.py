"""Export current logic-topic coverage and ranking for audit and review."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.models.core import Security
from app.db.models.ranking import (
    LogicTopic,
    LogicTopicRelation,
    RankingPriorItem,
    RankingPriorSnapshot,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from app.db.session import session_scope

    with session_scope() as session:
        rows = session.execute(
            select(LogicTopic, Security.name)
            .join(Security, Security.security_id == LogicTopic.security_id)
            .where(LogicTopic.status == "active")
            .order_by(LogicTopic.security_id, LogicTopic.topic_id)
        ).all()
        report = []
        for topic, company in rows:
            snapshot = session.scalar(
                select(RankingPriorSnapshot)
                .where(
                    RankingPriorSnapshot.security_id == topic.security_id,
                    RankingPriorSnapshot.direction == topic.direction,
                    RankingPriorSnapshot.horizon == topic.horizon,
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
            relation_counts = dict(
                session.execute(
                    select(LogicTopicRelation.object_type, func.count())
                    .where(
                        LogicTopicRelation.topic_id == topic.topic_id,
                        LogicTopicRelation.status == "active",
                    )
                    .group_by(LogicTopicRelation.object_type)
                ).all()
            )
            report.append(
                {
                    "security_id": topic.security_id,
                    "company": company,
                    "topic_id": topic.topic_id,
                    "name": topic.name,
                    "direction": topic.direction,
                    "horizon": topic.horizon,
                    "source_thesis_count": len(topic.source_thesis_ids or []),
                    "rank": item.final_rank if item else None,
                    "score": float(item.final_score) if item else None,
                    "feature_scores": dict(item.feature_scores or {}) if item else {},
                    "reason_codes": list(item.reason_codes or []) if item else [],
                    "relation_counts": relation_counts,
                    "snapshot_id": snapshot.snapshot_id if snapshot else None,
                }
            )
    payload = {
        "topic_count": len(report),
        "company_count": len({x["security_id"] for x in report}),
        "topics": report,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "topic_count": payload["topic_count"],
                "company_count": payload["company_count"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
