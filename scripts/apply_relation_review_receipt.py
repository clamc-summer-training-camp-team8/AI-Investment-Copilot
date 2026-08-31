"""校验并受控应用专业研究员关系复核回执；默认不提供隐式写入模式。"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import PROJECT_ROOT, settings
from app.core.enums import ConfirmationStatus, ImpactDirection
from app.db.repositories import build_uow
from app.db.session import session_scope
from app.services.permission import Actor
from app.services.relation_review_receipt import (
    RelationReviewPlan,
    RelationReviewReceipt,
    apply_relation_review,
    plan_relation_review,
)

DEFAULT_RECEIPT = (
    PROJECT_ROOT
    / "outputs"
    / "third-a-share-relation-review-20260831"
    / "relation_review_receipt.json"
)
_REQUIRED_ARTIFACT_ROLES = frozenset(
    {
        "candidate_snapshot",
        "primary_source_manifest",
        "review_template",
        "completed_review_workbook",
        "primary_source_2026",
        "primary_source_2025",
    }
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_and_validate_receipt(path: Path, *, expected_sha256: str) -> tuple[dict[str, Any], str]:
    resolved = path.resolve(strict=True)
    actual_sha256 = file_sha256(resolved)
    if actual_sha256 != expected_sha256.lower():
        raise ValueError(
            f"复核回执 SHA-256 不一致: expected={expected_sha256.lower()} actual={actual_sha256}"
        )
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "relation-review-receipt-v1":
        raise ValueError("不支持的复核回执 schema_version")
    if payload.get("application", {}).get("online_application_performed") is not False:
        raise ValueError("回执必须明确标记尚未执行线上应用")

    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("复核回执缺少 artifacts 清单")
    roles = [str(item.get("role")) for item in artifacts if isinstance(item, dict)]
    if len(roles) != len(set(roles)):
        raise ValueError("复核回执包含重复 artifact role")
    missing_roles = sorted(_REQUIRED_ARTIFACT_ROLES - set(roles))
    if missing_roles:
        raise ValueError(f"复核回执缺少必要附件: {missing_roles}")

    base_dir = resolved.parent
    for artifact in artifacts:
        relative_path = Path(str(artifact["path"]))
        if relative_path.is_absolute():
            raise ValueError(f"附件路径必须为相对路径: {relative_path}")
        artifact_path = (base_dir / relative_path).resolve(strict=True)
        if not artifact_path.is_relative_to(base_dir):
            raise ValueError(f"附件路径越过复核包目录: {relative_path}")
        expected_artifact_hash = str(artifact["sha256"]).lower()
        actual_artifact_hash = file_sha256(artifact_path)
        if actual_artifact_hash != expected_artifact_hash:
            raise ValueError(
                f"附件 SHA-256 不一致: role={artifact['role']} "
                f"expected={expected_artifact_hash} actual={actual_artifact_hash}"
            )
    return payload, actual_sha256


def parse_relation_review(payload: dict[str, Any]) -> RelationReviewReceipt:
    subject = payload["subject"]
    expected = payload["expected_candidate"]
    review = payload["review"]
    if review.get("primary_sources_verified") is not True:
        raise ValueError("一手来源尚未核验，不能应用复核回执")
    reviewed_at = datetime.fromisoformat(str(review["reviewed_at"]))
    return RelationReviewReceipt(
        relation_id=str(subject["relation_id"]),
        evidence_id=str(subject["evidence_id"]),
        thesis_id=str(subject["thesis_id"]),
        hypothesis_id=str(subject["hypothesis_id"]),
        expected_status=ConfirmationStatus(str(expected["status"])),
        expected_direction=ImpactDirection(str(expected["direction"])),
        expected_strength=expected.get("strength"),
        expected_reason=expected.get("reason"),
        decision=str(review["decision"]),
        final_direction=ImpactDirection(str(review["final_direction"])),
        final_strength=review.get("final_strength"),
        final_reason=str(review["reason"]),
        reviewer_id=str(review["reviewer_id"]),
        reviewed_at=reviewed_at,
    )


def _relation_state(plan: RelationReviewPlan) -> dict[str, Any]:
    return {
        "relation_id": plan.after.relation_id,
        "evidence_id": plan.after.evidence_id,
        "thesis_id": plan.after.thesis_id,
        "hypothesis_id": plan.after.hypothesis_id,
        "owner": plan.thesis.owner,
        "before": {
            "status": plan.before.status.value,
            "direction": plan.before.direction.value,
            "strength": plan.before.strength,
            "reason": plan.before.reason,
            "reviewed_by": plan.before.reviewed_by,
            "reviewed_at": plan.before.reviewed_at.isoformat() if plan.before.reviewed_at else None,
        },
        "after": {
            "status": plan.after.status.value,
            "direction": plan.after.direction.value,
            "strength": plan.after.strength,
            "reason": plan.after.reason,
            "reviewed_by": plan.after.reviewed_by,
            "reviewed_at": plan.after.reviewed_at.isoformat() if plan.after.reviewed_at else None,
        },
        "already_applied": plan.already_applied,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--expected-receipt-sha256", required=True)
    parser.add_argument("--operator", required=True, help="必须是目标投资逻辑负责人")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    payload, receipt_sha256 = load_and_validate_receipt(
        args.receipt,
        expected_sha256=args.expected_receipt_sha256,
    )
    receipt = parse_relation_review(payload)
    operator = Actor(user_id=args.operator)

    with session_scope() as session:
        uow = build_uow(session)
        plan = plan_relation_review(uow, receipt=receipt, operator=operator)
        if args.apply:
            apply_relation_review(
                uow,
                plan=plan,
                operator=operator,
                receipt_sha256=receipt_sha256,
                thresholds=settings.rules,
            )
        result = {
            "mode": "apply" if args.apply else "dry-run",
            "receipt_id": payload["receipt_id"],
            "receipt_sha256": receipt_sha256,
            "database_write_performed": bool(args.apply and not plan.already_applied),
            "relation": _relation_state(plan),
            "release_boundary": payload["application"],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
