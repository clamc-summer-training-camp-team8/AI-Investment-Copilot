"""Freeze a program-approved regression gold set for logic-topic ordering."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ranking", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    ranking = json.loads(args.ranking.read_text(encoding="utf-8"))
    review = json.loads(args.review.read_text(encoding="utf-8"))
    approved = {
        row["topic_id"]: row for row in review["judgements"] if row.get("primary_approved") is True
    }
    by_security: dict[str, list[dict]] = {}
    for row in ranking["topics"]:
        if row["security_id"] != "300274":
            by_security.setdefault(row["security_id"], []).append(row)

    cases = []
    for security_id, topics in sorted(by_security.items()):
        primary = next((row for row in topics if row["topic_id"] in approved), None)
        if primary is None:
            raise SystemExit(f"{security_id} 没有经复核批准的主主题，不能冻结金标")
        alternatives = [
            row
            for row in sorted(topics, key=lambda row: row["rank"])
            if row["topic_id"] != primary["topic_id"]
        ][:3]
        if len(alternatives) < 3:
            raise SystemExit(f"{security_id} 主题不足四个，不能生成五组排序金标")
        review_row = approved[primary["topic_id"]]
        shared = {
            "security_id": security_id,
            "company": primary["company"],
            "direction": primary["direction"],
            "horizon": primary["horizon"],
            "expected_primary_topic_id": primary["topic_id"],
            "expected_primary_name": primary["name"],
            "citation_locators": review_row.get("citation_locators", []),
        }
        cases.append(
            {
                **shared,
                "case_id": f"{security_id}-TOP1",
                "case_type": "top_1",
                "prompt": "在当前公司、方向和期限下，应优先返回哪条主投资逻辑？",
            }
        )
        for index, alternative in enumerate(alternatives, start=1):
            cases.append(
                {
                    **shared,
                    "case_id": f"{security_id}-PAIR-{index}",
                    "case_type": "pairwise",
                    "prompt": f"主逻辑与“{alternative['name']}”相比，哪条应优先？",
                    "comparison_topic_id": alternative["topic_id"],
                    "comparison_name": alternative["name"],
                }
            )
        cases.append(
            {
                **shared,
                "case_id": f"{security_id}-GATE",
                "case_type": "primary_gate",
                "prompt": "当前候选是否满足主投资逻辑的指标、直接证据与模型复核门槛？",
                "expected_primary_eligible": True,
            }
        )
    payload = {
        "version": "logic-topic-ranking-gold-v1-20260830",
        "annotation_status": "accepted_as_human_gold_by_product_owner",
        "acceptance_note": "沿用产品负责人已接受的程序金标口径；本集用于主题排序回归门禁，不能替代独立研究员双盲标注。",
        "case_count": len(cases),
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output": str(args.output), "case_count": len(cases)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
