"""Validate researcher annotations and the frozen gold file for MVP experiments."""

from __future__ import annotations

import csv
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

REVIEW_FIELDS = {
    "case_id",
    "company_name",
    "period",
    "candidate_direction",
    "proxy_gold_direction",
    "source_document_id",
    "source_url",
    "locator",
    "researcher_name",
    "researcher_decision",
    "researcher_direction",
    "researcher_reason",
    "reviewed_at",
}
VALID_DECISIONS = {"通过", "修改", "拒绝"}
VALID_DIRECTIONS = {"支持", "冲突", "中性", "无关"}
REFERENCE_FIELDS = (
    "company_name",
    "candidate_direction",
    "proxy_gold_direction",
    "source_document_id",
    "source_url",
    "locator",
)


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        missing = REVIEW_FIELDS - fields
        if missing:
            raise ValueError(f"{path.name}: 缺少字段 {sorted(missing)}")
        return [{key: (value or "").strip() for key, value in row.items()} for row in reader]


def _key(row: dict[str, str]) -> tuple[str, str]:
    return row["case_id"], row["period"]


def _event_index(events: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, str]]:
    result: dict[tuple[str, str], dict[str, str]] = {}
    for event in events:
        key = (event["case_id"], event["period"])
        result[key] = {
            "industry": event["industry"],
            "company_name": event["company_name"],
            "candidate_direction": event["candidate_direction"].value,
            "proxy_gold_direction": event["proxy_gold_direction"].value,
            "source_document_id": event["source_document_id"],
            "source_url": event["source_url"],
            "locator": event["locator"],
        }
    return result


def _validate_rows(
    label: str,
    rows: list[dict[str, str]],
    expected: dict[tuple[str, str], dict[str, str]],
    *,
    unique: bool,
) -> list[str]:
    errors: list[str] = []
    seen: Counter[tuple[str, str]] = Counter()
    seen_reviewer: set[tuple[str, str, str]] = set()
    for number, row in enumerate(rows, start=2):
        key = _key(row)
        seen[key] += 1
        reference = expected.get(key)
        if reference is None:
            errors.append(f"{label}:{number}: 未知事件 {key}")
            continue
        for field in REFERENCE_FIELDS:
            if row[field] != reference[field]:
                errors.append(f"{label}:{number}: {field} 与冻结事件不一致")
        if not row["researcher_name"]:
            errors.append(f"{label}:{number}: researcher_name 为空")
        reviewer_key = (*key, row["researcher_name"])
        if reviewer_key in seen_reviewer:
            errors.append(f"{label}:{number}: 同一研究员重复标注 {key}")
        seen_reviewer.add(reviewer_key)
        if row["researcher_decision"] not in VALID_DECISIONS:
            errors.append(f"{label}:{number}: researcher_decision 非法")
        if row["researcher_direction"] not in VALID_DIRECTIONS:
            errors.append(f"{label}:{number}: researcher_direction 非法")
        if not row["researcher_reason"]:
            errors.append(f"{label}:{number}: researcher_reason 为空")
        try:
            reviewed_at = datetime.fromisoformat(row["reviewed_at"])
            if reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None:
                errors.append(f"{label}:{number}: reviewed_at 必须带时区")
        except ValueError:
            errors.append(f"{label}:{number}: reviewed_at 不是 ISO 8601 时间")

    actual_keys = set(seen)
    expected_keys = set(expected)
    if actual_keys != expected_keys:
        errors.append(
            f"{label}: 事件集合不完整，缺少 {sorted(expected_keys - actual_keys)}，"
            f"多出 {sorted(actual_keys - expected_keys)}"
        )
    if unique and any(count != 1 for count in seen.values()):
        errors.append(f"{label}: 每个事件必须恰好一行")
    return errors


def validate_researcher_reviews(
    events: list[dict[str, Any]],
    annotations_path: Path,
    independent_path: Path,
    gold_path: Path,
) -> dict[str, Any]:
    """Validate coverage, double review and final adjudication without mutating inputs."""
    expected = _event_index(events)
    annotations = _read(annotations_path)
    independent = _read(independent_path)
    gold = _read(gold_path)

    errors = _validate_rows("annotations", annotations, expected, unique=False)
    errors.extend(_validate_rows("independent", independent, expected, unique=True))
    errors.extend(_validate_rows("gold", gold, expected, unique=True))

    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in annotations:
        grouped[_key(row)].append(row)
    doubles = {key: rows for key, rows in grouped.items() if len(rows) >= 2}
    minimum_double = math.ceil(len(expected) * 0.2)
    if len(doubles) < minimum_double:
        errors.append(f"双人复核不足：要求至少 {minimum_double}，实际 {len(doubles)}")

    double_by_industry: Counter[str] = Counter()
    direction_agreements = 0
    decision_agreements = 0
    for key, rows in doubles.items():
        double_by_industry[expected[key]["industry"]] += 1
        direction_agreements += len({row["researcher_direction"] for row in rows}) == 1
        decision_agreements += len({row["researcher_decision"] for row in rows}) == 1
    for industry in {item["industry"] for item in expected.values()}:
        if double_by_industry[industry] < 2:
            errors.append(f"{industry}: 双人复核少于 2 个事件")

    primary = {key: rows[0] for key, rows in grouped.items()}
    independent_by_key = {_key(row): row for row in independent}
    gold_by_key = {_key(row): row for row in gold}
    candidate_gold = sum(
        gold_by_key[key]["researcher_direction"] == reference["candidate_direction"]
        for key, reference in expected.items()
        if key in gold_by_key
    )
    primary_gold = sum(
        primary[key]["researcher_direction"] == gold_by_key[key]["researcher_direction"]
        for key in expected
        if key in primary and key in gold_by_key
    )
    independent_gold = sum(
        independent_by_key[key]["researcher_direction"] == gold_by_key[key]["researcher_direction"]
        for key in expected
        if key in independent_by_key and key in gold_by_key
    )

    return {
        "status": "PASS" if not errors else "FAIL",
        "annotation_version": "researcher-gold-v1",
        "errors": errors,
        "annotation_rows": len(annotations),
        "event_count": len(expected),
        "double_reviewed_events": len(doubles),
        "minimum_double_reviewed_events": minimum_double,
        "double_review_by_industry": dict(sorted(double_by_industry.items())),
        "double_direction_agreement": {
            "numerator": direction_agreements,
            "denominator": len(doubles),
        },
        "double_decision_agreement": {
            "numerator": decision_agreements,
            "denominator": len(doubles),
        },
        "primary_gold_direction_agreement": {
            "numerator": primary_gold,
            "denominator": len(expected),
        },
        "independent_gold_direction_agreement": {
            "numerator": independent_gold,
            "denominator": len(expected),
        },
        "candidate_gold_direction_agreement": {
            "numerator": candidate_gold,
            "denominator": len(expected),
            "interpretation": "确定性规则候选与独立研究员金标的一致率，不是AI模型准确率",
        },
    }


def apply_researcher_review(result: dict[str, Any], review: dict[str, Any]) -> None:
    """Attach immutable review metrics and update only the corresponding gate."""
    result["researcher_review"] = review
    result["metrics"]["researcher_review"] = review
    gate = next(
        item for item in result["gates"] if item["gate"] == "independent_researcher_gold_review"
    )
    gate["status"] = review["status"]
    gate["denominator"] = review["event_count"]
    if review["errors"]:
        gate["reason"] = "；".join(review["errors"][:3])
    else:
        gate.pop("reason", None)
        gate["numerator"] = review["event_count"]
        result["annotation_version"] = review["annotation_version"]
        result["limitations"] = [
            item
            for item in result.get("limitations", [])
            if not item.startswith("代理复核不是独立业务金标")
        ]
        result["limitations"].append(
            "独立研究员金标已覆盖27个事件，但双人复核仅覆盖最低要求的6个事件；"
            "一致率不能替代更大样本的标注质量审计。"
        )
