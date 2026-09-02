from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.restore_reviewed_relation_candidate import _validate_candidate_snapshot

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PACKAGE = PROJECT_ROOT / "outputs" / "third-a-share-relation-review-20260831"


def _artifacts() -> tuple[dict, dict]:
    snapshot = json.loads((PACKAGE / "candidate_snapshot.json").read_text(encoding="utf-8"))
    receipt = json.loads(
        (PACKAGE / "relation_review_receipt.json").read_text(encoding="utf-8")
    )
    return snapshot, receipt


def test_candidate_snapshot_matches_review_receipt() -> None:
    snapshot, receipt = _artifacts()

    candidate = _validate_candidate_snapshot(snapshot, receipt)

    assert candidate["relation_id"] == "REL-ea2dd5a4df3547af"
    assert candidate["security_id"] == "002594"


def test_candidate_snapshot_drift_is_rejected() -> None:
    snapshot, receipt = _artifacts()
    drifted = copy.deepcopy(snapshot)
    drifted["candidate_relation"]["candidate_strength"] = "低"

    with pytest.raises(ValueError, match="候选快照与复核回执不一致"):
        _validate_candidate_snapshot(drifted, receipt)
