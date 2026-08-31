"""Verify archived-revision coverage, object versions and sampled content SHA-256."""

from __future__ import annotations

import argparse
import json
import os
import random
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

from sqlalchemy import func, select

from app.core.config import settings
from app.db.models.assets import DocumentRevision
from app.db.models.core import Document
from app.db.session import session_scope
from app.services.object_store import S3ObjectStore


def _archived_revisions() -> tuple[int, list[tuple[str, str, str | None, str]]]:
    with session_scope() as session:
        active_documents = int(
            session.scalar(
                select(func.count()).select_from(Document).where(Document.deleted_at.is_(None))
            )
            or 0
        )
        rows = session.execute(
            select(
                DocumentRevision.canonical_document_id,
                DocumentRevision.object_key,
                DocumentRevision.object_version_id,
                DocumentRevision.content_hash,
            )
            .join(Document, Document.document_id == DocumentRevision.canonical_document_id)
            .where(
                Document.deleted_at.is_(None),
                DocumentRevision.object_key.is_not(None),
                DocumentRevision.tombstoned_at.is_(None),
            )
            .order_by(
                DocumentRevision.canonical_document_id,
                DocumentRevision.created_at.desc(),
                DocumentRevision.revision_id.desc(),
            )
            .distinct(DocumentRevision.canonical_document_id)
        ).all()
    return active_documents, [
        (str(document_id), str(object_key), version_id, str(content_hash))
        for document_id, object_key, version_id, content_hash in rows
    ]


def _file_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(*, sample_size: int, seed: int) -> dict[str, object]:
    endpoint_host = urlparse(settings.object_store_endpoint).hostname
    if endpoint_host in {"127.0.0.1", "localhost", "::1"}:
        current = {item for item in os.environ.get("NO_PROXY", "").split(",") if item}
        current.update({"127.0.0.1", "localhost", "::1"})
        os.environ["NO_PROXY"] = ",".join(sorted(current))
    active_documents, revisions = _archived_revisions()
    store = S3ObjectStore(settings)
    missing = [
        document_id
        for document_id, object_key, version_id, _ in revisions
        if not store.exists(object_key=object_key, version_id=version_id)
    ]
    available = [item for item in revisions if item[0] not in set(missing)]
    chosen = random.Random(seed).sample(available, min(sample_size, len(available)))
    mismatches: list[str] = []
    with TemporaryDirectory(prefix="aic-archive-verify-") as temp:
        root = Path(temp)
        for index, (document_id, object_key, version_id, expected_hash) in enumerate(chosen):
            target = root / f"{index}.blob"
            store.download(
                object_key=object_key,
                destination=target,
                version_id=version_id,
            )
            if _file_hash(target) != expected_hash:
                mismatches.append(document_id)
    return {
        "schema_version": "source-archive-verification-v1",
        "verified_at": datetime.now(UTC).isoformat(),
        "active_documents": active_documents,
        "archived_documents": len(revisions),
        "coverage_complete": len(revisions) == active_documents,
        "missing_object_versions": missing,
        "sample_seed": seed,
        "sampled_content_hashes": len(chosen),
        "content_hash_mismatches": mismatches,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-size", type=int, default=25)
    parser.add_argument("--seed", type=int, default=20260830)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = verify(sample_size=max(0, args.sample_size), seed=args.seed)
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")
    print(output)
    if (
        not report["coverage_complete"]
        or report["missing_object_versions"]
        or report["content_hash_mismatches"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
