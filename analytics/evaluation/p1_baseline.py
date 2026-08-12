"""P1 unified quality and workflow baseline from independent human gold.

The 59-row blind set is independent of the evaluated annotation pipeline.  It
covers event screening, security ownership, hypothesis matching and direction.
Operational metrics are read from persisted human-review/model-audit records;
missing denominators or price configuration remain null instead of fabricated.
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime

from sqlalchemy import text

from app.core.config import PROJECT_ROOT, settings
from app.db.session import session_scope

GOLD = (
    PROJECT_ROOT
    / "real_data/dataset/blind_annotation_result/mentor_blind_annotation_v2_annotated.csv"
)
EVENTS = PROJECT_ROOT / "real_data/dataset/events.csv"
OUTPUT = PROJECT_ROOT / "analytics/experiments/20260813-p1-evaluation-rag-pilot"
GOLD_VERSION = "mentor-blind-gold-v2-20260811"


def _rate(numerator: int, denominator: int) -> dict[str, int | float | None]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": round(numerator / denominator, 4) if denominator else None,
    }


def _load() -> list[tuple[dict[str, str], dict[str, str]]]:
    with GOLD.open(encoding="utf-8-sig") as stream:
        gold = list(csv.DictReader(stream))
    with EVENTS.open(encoding="utf-8-sig") as stream:
        events = {
            (row["company"], row["disclosure_time"][:10], row["title"]): row
            for row in csv.DictReader(stream)
        }
    return [(row, events[(row["公司"], row["披露日期"], row["公告标题"])]) for row in gold]


def _quality(paired: list[tuple[dict[str, str], dict[str, str]]]) -> dict[str, object]:
    gold_relevant = [bool(gold["关联假设"]) for gold, _ in paired]
    predicted_relevant = [bool(event["annotator_a_hypothesis"]) for _, event in paired]
    tp = sum(
        gold and predicted
        for gold, predicted in zip(gold_relevant, predicted_relevant, strict=False)
    )
    fp = sum(
        not gold and predicted
        for gold, predicted in zip(gold_relevant, predicted_relevant, strict=False)
    )
    fn = sum(
        gold and not predicted
        for gold, predicted in zip(gold_relevant, predicted_relevant, strict=False)
    )
    relevant_pairs = [
        (gold, event)
        for gold, event in paired
        if gold["关联假设"] and event["annotator_a_hypothesis"]
    ]
    return {
        "event_extraction": {
            "precision": _rate(tp, tp + fp),
            "recall": _rate(tp, tp + fn),
            "miss_rate": _rate(fn, tp + fn),
        },
        "security_assignment": {
            "accuracy": _rate(
                sum(gold["证券代码"] == event["security_id"] for gold, event in paired),
                len(paired),
            )
        },
        "hypothesis_matching": {
            "accuracy": _rate(
                sum(gold["关联假设"] == event["annotator_a_hypothesis"] for gold, event in paired),
                len(paired),
            )
        },
        "direction": {
            "accuracy_on_shared_relevant": _rate(
                sum(
                    gold["影响方向"] == event["annotator_a_direction"]
                    for gold, event in relevant_pairs
                ),
                len(relevant_pairs),
            )
        },
    }


def _operations() -> dict[str, object]:
    with session_scope() as session:
        candidates, accepted, rejected, review_seconds = session.execute(
            text(
                """SELECT count(*),
                          count(*) FILTER (WHERE confirmation_status='已确认'),
                          count(*) FILTER (WHERE confirmation_status='已驳回'),
                          avg(extract(epoch FROM (confirmed_at-created_at)))
                            FILTER (WHERE confirmed_at IS NOT NULL)
                   FROM evidence"""
            )
        ).one()
        events, duplicate_fingerprints = session.execute(
            text(
                """SELECT count(*), count(*)-count(DISTINCT fingerprint)
                   FROM event"""
            )
        ).one()
        suppressed_duplicates, completed_events = session.execute(
            text(
                """SELECT coalesce(sum((result->>'duplicate_event_count')::integer), 0),
                          coalesce(sum((result->>'event_count')::integer), 0)
                   FROM document_processing_job
                   WHERE status='complete'
                     AND result ? 'duplicate_event_count'
                     AND result ? 'event_count'"""
            )
        ).one()
        calls = session.execute(
            text(
                """SELECT detail FROM audit_log
                   WHERE action='模型调用' ORDER BY occurred_at"""
            )
        ).scalars()
        input_tokens = output_tokens = 0
        metered_calls = 0
        for detail in calls:
            metadata = (detail or {}).get("model_metadata", {})
            usage = metadata.get("usage", {}) if isinstance(metadata, dict) else {}
            if not isinstance(usage, dict):
                continue
            prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
            completion = usage.get("completion_tokens", usage.get("output_tokens"))
            if isinstance(prompt, int) or isinstance(completion, int):
                metered_calls += 1
                input_tokens += int(prompt or 0)
                output_tokens += int(completion or 0)
    cost = None
    if (
        settings.llm_input_cost_per_million is not None
        and settings.llm_output_cost_per_million is not None
    ):
        cost = round(
            input_tokens / 1_000_000 * settings.llm_input_cost_per_million
            + output_tokens / 1_000_000 * settings.llm_output_cost_per_million,
            6,
        )
    reviewed = accepted + rejected
    return {
        "candidate_evidence": candidates,
        "reviewed_evidence": reviewed,
        "review_completion_rate": _rate(reviewed, candidates),
        "adoption_rate": _rate(accepted, candidates),
        "rejection_rate": _rate(rejected, candidates),
        "adoption_rate_among_reviewed": _rate(accepted, reviewed),
        "rejection_rate_among_reviewed": _rate(rejected, reviewed),
        "mean_human_review_minutes": (
            round(float(review_seconds) / 60, 2) if review_seconds is not None else None
        ),
        "duplicate_reminder_rate": _rate(duplicate_fingerprints, events),
        "duplicate_event_suppression_rate": _rate(
            suppressed_duplicates, suppressed_duplicates + completed_events
        ),
        "model_usage": {
            "metered_calls": metered_calls,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost": cost,
            "currency": "configured-unit" if cost is not None else None,
        },
    }


def main() -> None:
    paired = _load()
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "gold_version": GOLD_VERSION,
        "sample_size": len(paired),
        "quality": _quality(paired),
        "operations": _operations(),
        "limitations": [
            "独立金标为单人盲标，尚不能计算标注者间一致性。",
            "成本只在审计记录含 token usage 且配置单价时计算。",
            "人工耗时只统计已持久化 confirmed_at 的候选证据。",
            "采纳率和驳回率同时给出全体候选及已复核子集口径；未复核时后者保持 null。",
            "重复提醒率用持久化事件 fingerprint 检查，任务内已拦截的重复另报 suppression rate。",
        ],
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "p1_baseline.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
