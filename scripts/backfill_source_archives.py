"""Append historical source objects, verified revisions and archive-only runs.

The command is resumable: documents with an active archived revision are skipped.  It never
rewrites legacy revisions or ingestion artifacts.  Download failures are themselves appended as
failed ingestion runs so a retry does not erase the audit trail.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from sqlalchemy import exists, select

from app.core.config import PROJECT_ROOT, settings
from app.core.domain import DocumentRevisionRecord, IngestionRunRecord
from app.db.models.assets import DocumentRevision, Source
from app.db.models.core import Document
from app.db.repositories.assets import SqlAssetRepo
from app.db.session import session_scope
from app.services.object_store import S3ObjectStore, object_key_for

POLICY_PATH = PROJECT_ROOT / "governance" / "source-policies.json"
ARCHIVE_PARSER_VERSION = "source-archive-v1"
ARCHIVE_CHUNKER_VERSION = "archive-only-v1"
ARCHIVE_EXTRACTOR_VERSION = "none"
_THREAD_LOCAL = threading.local()


@dataclass(frozen=True)
class Policy:
    policy_id: str
    source_id: str
    name: str
    source_type: str
    authorization_status: str
    authorization_basis: str
    verified_by: str
    verified_at: datetime
    allowed_hosts: tuple[str, ...] = ()
    document_id_prefixes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Candidate:
    document_id: str
    title: str
    source_filename: str
    legacy_revision_id: str
    source_url: str | None
    raw_path: str | None
    body: str | None
    published_at: datetime
    is_illustrative: bool


@dataclass(frozen=True)
class Materialized:
    candidate: Candidate
    path: Path
    digest: str
    byte_size: int
    media_type: str
    source_url: str | None
    policy: Policy
    content_status: str


def _load_policy() -> tuple[dict[str, Policy], dict[str, dict[str, str]]]:
    payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    policies = {
        item["policy_id"]: Policy(
            policy_id=item["policy_id"],
            source_id=item["source_id"],
            name=item["name"],
            source_type=item["source_type"],
            authorization_status=item["authorization_status"],
            authorization_basis=item["authorization_basis"],
            verified_by=item["verified_by"],
            verified_at=datetime.fromisoformat(item["verified_at"]),
            allowed_hosts=tuple(item.get("allowed_hosts", [])),
            document_id_prefixes=tuple(item.get("document_id_prefixes", [])),
        )
        for item in payload["policies"]
    }
    overrides = {item["document_id"]: item for item in payload["local_source_overrides"]}
    return policies, overrides


def _candidates(*, limit: int | None, document_id: str | None) -> list[Candidate]:
    with session_scope() as session:
        archived = (
            exists()
            .where(
                DocumentRevision.canonical_document_id == Document.document_id,
                DocumentRevision.object_key.is_not(None),
                DocumentRevision.tombstoned_at.is_(None),
            )
            .correlate(Document)
        )
        statement = (
            select(Document, DocumentRevision)
            .join(
                DocumentRevision,
                DocumentRevision.canonical_document_id == Document.document_id,
            )
            .where(
                Document.deleted_at.is_(None),
                DocumentRevision.object_key.is_(None),
                ~archived,
            )
            .order_by(Document.document_id, DocumentRevision.created_at)
            .distinct(Document.document_id)
        )
        if document_id:
            statement = statement.where(Document.document_id == document_id)
        if limit is not None:
            statement = statement.limit(limit)
        return [
            Candidate(
                document_id=document.document_id,
                title=document.title or document.document_id,
                source_filename=revision.source_filename,
                legacy_revision_id=revision.revision_id,
                source_url=revision.source_url,
                raw_path=document.raw_path,
                body=document.body,
                published_at=document.published_at,
                is_illustrative=document.is_illustrative,
            )
            for document, revision in session.execute(statement)
        ]


def _client(timeout_seconds: float) -> httpx.Client:
    client = getattr(_THREAD_LOCAL, "client", None)
    if client is None:
        client = httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 15.0)),
            headers={"User-Agent": "AI-Investment-Copilot-Asset-Governance/1.0"},
        )
        _THREAD_LOCAL.client = client
    return client


def _download(
    candidate: Candidate,
    *,
    destination: Path,
    policies: dict[str, Policy],
    overrides: dict[str, dict[str, str]],
    timeout_seconds: float,
    max_bytes: int,
) -> Materialized:
    override = overrides.get(candidate.document_id)
    if candidate.source_url:
        source_url = candidate.source_url.replace("http://", "https://", 1)
        policy = policies["cninfo-public-disclosure-v1"]
        path = destination / f"{candidate.document_id}.pdf"
        _download_http(source_url, path, policy, timeout_seconds, max_bytes)
        media_type = "application/pdf"
        content_status = "原件已归档"
    elif override:
        source_url = override["source_url"]
        policy = policies[override["policy_id"]]
        raw_path = Path(candidate.raw_path or "")
        if not raw_path.is_file():
            raise ValueError(f"本地遗留原件不存在: {candidate.document_id}")
        path = destination / f"{candidate.document_id}{raw_path.suffix.lower() or '.bin'}"
        shutil.copyfile(raw_path, path)
        media_type = "application/pdf" if path.suffix == ".pdf" else "application/octet-stream"
        content_status = "原件已归档"
    elif (
        candidate.is_illustrative
        and candidate.body
        and candidate.document_id.startswith("DOC-DEMO-")
    ):
        source_url = None
        policy = policies["project-synthetic-sample-v1"]
        package = {
            "schema_version": "synthetic-source-package-v1",
            "document_id": candidate.document_id,
            "title": candidate.title,
            "is_illustrative": True,
            "content": candidate.body,
        }
        path = destination / f"{candidate.document_id}.json"
        path.write_text(
            json.dumps(package, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        media_type = "application/json"
        content_status = "合成样例"
    else:
        raise ValueError(f"没有经过核验的原件来源: {candidate.document_id}")

    digest = _file_hash(path)
    if override and digest != override["sha256"]:
        raise ValueError(f"本地遗留原件哈希与核验清单不一致: {candidate.document_id}")
    if path.stat().st_size > max_bytes:
        raise ValueError(f"原件超过单文件上限: {candidate.document_id}")
    return Materialized(
        candidate=candidate,
        path=path,
        digest=digest,
        byte_size=path.stat().st_size,
        media_type=media_type,
        source_url=source_url,
        policy=policy,
        content_status=content_status,
    )


def _download_http(
    url: str, path: Path, policy: Policy, timeout_seconds: float, max_bytes: int
) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in policy.allowed_hosts:
        raise ValueError(f"来源 URL 不符合授权策略: {url}")
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with _client(timeout_seconds).stream("GET", url) as response:
                response.raise_for_status()
                final = urlparse(str(response.url))
                if final.scheme != "https" or final.hostname not in policy.allowed_hosts:
                    raise ValueError(f"来源重定向到未授权域名: {response.url}")
                declared = int(response.headers.get("content-length", "0") or 0)
                if declared > max_bytes:
                    raise ValueError(f"原件超过单文件上限: {declared}")
                size = 0
                with path.open("xb") as handle:
                    for chunk in response.iter_bytes(1024 * 1024):
                        size += len(chunk)
                        if size > max_bytes:
                            raise ValueError(f"原件超过单文件上限: {size}")
                        handle.write(chunk)
            with path.open("rb") as handle:
                signature = handle.read(5)
            if signature != b"%PDF-":
                raise ValueError("公开原件不是有效 PDF")
            return
        except (httpx.HTTPError, OSError) as exc:
            path.unlink(missing_ok=True)
            last_error = exc
            if attempt < 2:
                time.sleep(2**attempt)
    raise RuntimeError(f"下载失败: {url}") from last_error


def _persist_success(item: Materialized, store: S3ObjectStore) -> str:
    suffix = item.path.suffix.lower()
    key = object_key_for(content_hash=item.digest, suffix=suffix, tenant="historical")
    stored = store.put_immutable(
        path=item.path,
        object_key=key,
        content_hash=item.digest,
        media_type=item.media_type,
    )
    revision_id = f"DREV-HIST-{sha256(f'{item.candidate.document_id}|{item.digest}'.encode()).hexdigest()[:40]}"
    run_id = (
        f"IRUN-ARCH-{sha256(f'{revision_id}|{ARCHIVE_PARSER_VERSION}'.encode()).hexdigest()[:40]}"
    )
    with session_scope() as session:
        existing = session.get(DocumentRevision, revision_id)
        if existing is not None:
            return "already_archived"
        source = session.get(Source, item.policy.source_id)
        if source is None:
            source = Source(
                source_id=item.policy.source_id,
                name=item.policy.name,
                source_type=item.policy.source_type,
                authorization_status=item.policy.authorization_status,
                base_url=item.source_url,
                active=True,
            )
            session.add(source)
        source.authorization_status = item.policy.authorization_status
        source.authorization_basis = item.policy.authorization_basis
        source.authorization_verified_by = item.policy.verified_by
        source.authorization_verified_at = item.policy.verified_at
        session.flush()
        repo = SqlAssetRepo(session)
        repo.add_revision(
            DocumentRevisionRecord(
                revision_id=revision_id,
                document_id=item.candidate.document_id,
                canonical_document_id=item.candidate.document_id,
                content_hash=item.digest,
                source_filename=item.path.name,
                object_key=stored.object_key,
                object_version_id=stored.version_id,
                media_type=item.media_type,
                byte_size=item.byte_size,
                source_id=item.policy.source_id,
                source_url=item.source_url,
                authorization_status=item.policy.authorization_status,
                authorization_basis=item.policy.authorization_basis,
                authorization_verified_by=item.policy.verified_by,
                authorization_verified_at=item.policy.verified_at,
                content_status=item.content_status,
                uploaded_by="asset-governance-backfill",
                published_at=item.candidate.published_at,
            )
        )
        repo.add_run(
            IngestionRunRecord(
                run_id=run_id,
                revision_id=revision_id,
                parser_version=ARCHIVE_PARSER_VERSION,
                chunker_version=ARCHIVE_CHUNKER_VERSION,
                extractor_version=ARCHIVE_EXTRACTOR_VERSION,
                status="succeeded",
                quality_summary={
                    "archive_only": True,
                    "append_only": True,
                    "policy_id": item.policy.policy_id,
                    "content_status": item.content_status,
                    "source_body_extracted": False,
                },
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
            )
        )
    return "archived"


def _persist_failure(candidate: Candidate, reason: str) -> None:
    with session_scope() as session:
        if session.get(DocumentRevision, candidate.legacy_revision_id) is None:
            return
        SqlAssetRepo(session).add_run(
            IngestionRunRecord(
                run_id=f"IRUN-ARCHFAIL-{uuid4().hex}",
                revision_id=candidate.legacy_revision_id,
                parser_version=ARCHIVE_PARSER_VERSION,
                chunker_version=ARCHIVE_CHUNKER_VERSION,
                extractor_version=ARCHIVE_EXTRACTOR_VERSION,
                status="failed",
                quality_summary={"archive_only": True, "append_only": True},
                error=reason[:2000],
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
            )
        )


def _file_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backfill(
    *,
    limit: int | None,
    document_id: str | None,
    workers: int,
    timeout_seconds: float,
    max_bytes: int,
    dry_run: bool,
) -> dict[str, object]:
    policies, overrides = _load_policy()
    candidates = _candidates(limit=limit, document_id=document_id)
    report: dict[str, object] = {
        "schema_version": "source-archive-backfill-report-v1",
        "started_at": datetime.now(UTC).isoformat(),
        "candidate_count": len(candidates),
        "archived": 0,
        "already_archived": 0,
        "failed": 0,
        "failures": [],
    }
    if dry_run or not candidates:
        report["dry_run"] = dry_run
        report["finished_at"] = datetime.now(UTC).isoformat()
        return report

    endpoint_host = urlparse(settings.object_store_endpoint).hostname
    if endpoint_host in {"127.0.0.1", "localhost", "::1"}:
        no_proxy = {item.strip() for item in os.environ.get("NO_PROXY", "").split(",") if item}
        no_proxy.update({"127.0.0.1", "localhost", "::1"})
        os.environ["NO_PROXY"] = ",".join(sorted(no_proxy))
    store = S3ObjectStore(settings)
    store.ensure_bucket()
    with TemporaryDirectory(prefix="aic-source-backfill-") as temp:
        destination = Path(temp)
        with ThreadPoolExecutor(max_workers=max(1, min(workers, 32))) as pool:
            futures = {
                pool.submit(
                    _download,
                    candidate,
                    destination=destination,
                    policies=policies,
                    overrides=overrides,
                    timeout_seconds=timeout_seconds,
                    max_bytes=max_bytes,
                ): candidate
                for candidate in candidates
            }
            for future in as_completed(futures):
                candidate = futures[future]
                materialized: Materialized | None = None
                try:
                    materialized = future.result()
                    outcome = _persist_success(materialized, store)
                    report[outcome] = int(report[outcome]) + 1
                except Exception as exc:
                    reason = f"{type(exc).__name__}: {exc}"
                    _persist_failure(candidate, reason)
                    report["failed"] = int(report["failed"]) + 1
                    failures = report["failures"]
                    assert isinstance(failures, list)
                    failures.append({"document_id": candidate.document_id, "reason": reason})
                finally:
                    if materialized is not None:
                        materialized.path.unlink(missing_ok=True)
                completed = (
                    int(report["archived"])
                    + int(report["already_archived"])
                    + int(report["failed"])
                )
                if completed % 100 == 0 or completed == len(candidates):
                    print(
                        f"progress {completed}/{len(candidates)} "
                        f"archived={report['archived']} failed={report['failed']}",
                        flush=True,
                    )
    report["finished_at"] = datetime.now(UTC).isoformat()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--document-id")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--max-bytes", type=int, default=250 * 1024 * 1024)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = backfill(
        limit=args.limit,
        document_id=args.document_id,
        workers=args.workers,
        timeout_seconds=args.timeout_seconds,
        max_bytes=args.max_bytes,
        dry_run=args.dry_run,
    )
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")
    print(output)
    if int(report["failed"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
