from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.apply_relation_review_receipt import load_and_validate_receipt


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _package(tmp_path: Path) -> Path:
    artifacts = []
    for role in (
        "candidate_snapshot",
        "primary_source_manifest",
        "review_template",
        "completed_review_workbook",
        "primary_source_2026",
        "primary_source_2025",
    ):
        file_path = tmp_path / f"{role}.bin"
        file_path.write_bytes(role.encode())
        artifacts.append({"role": role, "path": file_path.name, "sha256": _sha256(file_path)})
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "schema_version": "relation-review-receipt-v1",
                "application": {"online_application_performed": False},
                "artifacts": artifacts,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return receipt


def test_load_receipt_verifies_every_attachment_hash(tmp_path: Path) -> None:
    receipt = _package(tmp_path)

    payload, actual_hash = load_and_validate_receipt(receipt, expected_sha256=_sha256(receipt))

    assert payload["schema_version"] == "relation-review-receipt-v1"
    assert actual_hash == _sha256(receipt)


def test_load_receipt_rejects_attachment_drift(tmp_path: Path) -> None:
    receipt = _package(tmp_path)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    (tmp_path / payload["artifacts"][0]["path"]).write_bytes(b"changed")

    with pytest.raises(ValueError, match="附件 SHA-256 不一致"):
        load_and_validate_receipt(receipt, expected_sha256=_sha256(receipt))
