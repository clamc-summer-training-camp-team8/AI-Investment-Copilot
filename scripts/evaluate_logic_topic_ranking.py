"""Evaluate frozen logic-topic ranking gold against a materialized ranking report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--ranking", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    gold = json.loads(args.gold.read_text(encoding="utf-8"))
    ranking = json.loads(args.ranking.read_text(encoding="utf-8"))
    topics = {row["topic_id"]: row for row in ranking["topics"]}
    results = []
    for case in gold["cases"]:
        primary = topics.get(case["expected_primary_topic_id"])
        if primary is None:
            results.append({**case, "passed": False, "failure": "expected_topic_missing"})
            continue
        eligible = (
            "PRIMARY_TOPIC_ELIGIBLE" in primary["reason_codes"]
            and "MODEL_PRIMARY_REJECTED" not in primary["reason_codes"]
        )
        if case["case_type"] == "top_1":
            passed = primary["rank"] == 1 and eligible
            detail = {"actual_rank": primary["rank"], "primary_eligible": eligible}
        elif case["case_type"] == "pairwise":
            alternative = topics.get(case["comparison_topic_id"])
            passed = alternative is not None and primary["rank"] < alternative["rank"] and eligible
            detail = {
                "actual_rank": primary["rank"],
                "comparison_rank": alternative["rank"] if alternative else None,
                "primary_eligible": eligible,
            }
        else:
            passed = eligible == case["expected_primary_eligible"]
            detail = {"primary_eligible": eligible}
        results.append({**case, "passed": passed, **detail})
    passed_count = sum(row["passed"] for row in results)
    top1 = [row for row in results if row["case_type"] == "top_1"]
    pairwise = [row for row in results if row["case_type"] == "pairwise"]
    gates = [row for row in results if row["case_type"] == "primary_gate"]
    summary = {
        "cases": len(results),
        "passed": passed_count,
        "accuracy": round(passed_count / len(results), 4) if results else 0.0,
        "top_1_accuracy": round(sum(row["passed"] for row in top1) / len(top1), 4) if top1 else 0.0,
        "pairwise_accuracy": round(sum(row["passed"] for row in pairwise) / len(pairwise), 4)
        if pairwise
        else 0.0,
        "primary_gate_accuracy": round(sum(row["passed"] for row in gates) / len(gates), 4)
        if gates
        else 0.0,
    }
    summary["gate"] = {
        "status": "accepted_program_gold_regression_gate",
        "passed": summary["top_1_accuracy"] >= 0.8
        and summary["pairwise_accuracy"] >= 0.8
        and summary["primary_gate_accuracy"] == 1.0,
        "limitations": "金标由当前模型复核和规则快照构造，适合作为回归门禁；独立研究员双盲评测仍待建立。",
    }
    payload = {
        "gold_version": gold["version"],
        "annotation_status": gold["annotation_status"],
        "summary": summary,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
