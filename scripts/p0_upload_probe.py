"""Upload one fresh TXT through the public API and verify the complete P0-0 chain."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

import httpx
from sqlalchemy import text

from app.core.config import PROJECT_ROOT, settings
from app.db.session import session_scope
from app.services.object_store import S3ObjectStore


def main() -> None:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    marker = f"P0环境复验标记{stamp}"
    probe = PROJECT_ROOT / ".runtime" / f"p0-upload-probe-{stamp}.txt"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text(
        f"{marker}\n公司披露新签订单金额同比增长35%，营业收入展望改善。\n"
        "该资料用于本地交付链路复验，不构成投资建议。\n",
        encoding="utf-8",
    )
    headers = {"X-User-Id": "analyst-mvp", "X-User-Teams": "analyst-mvp"}
    try:
        with probe.open("rb") as stream:
            response = httpx.post(
                "http://127.0.0.1:8000/api/jobs/documents",
                headers=headers,
                files={"file": (probe.name, stream, "text/plain")},
                data={
                    "published_at": datetime.now(UTC).isoformat(),
                    "security_id": "600276",
                    "view": "验证订单增长对收入假设的候选影响",
                },
                timeout=30,
            )
        response.raise_for_status()
        accepted = response.json()
        deadline = time.monotonic() + 60
        while True:
            snapshot = httpx.get(
                f"http://127.0.0.1:8000/api/jobs/{accepted['job_id']}",
                headers=headers,
                timeout=10,
            ).json()
            if snapshot["status"] in {"complete", "not_found"}:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("upload job did not finish")
            time.sleep(0.5)
        if not snapshot.get("success"):
            raise RuntimeError(json.dumps(snapshot, ensure_ascii=False))
        with session_scope() as session:
            row = (
                session.execute(
                    text(
                        """SELECT r.revision_id,r.object_key,r.object_version_id,r.content_hash,
                              ir.run_id,ir.status,ir.segment_count,ir.event_count,ir.embedding_version,
                              (SELECT count(*) FROM ingestion_artifact a WHERE a.run_id=ir.run_id) artifacts,
                              (SELECT count(*) FROM segment_search_index i WHERE i.ingestion_run_id=ir.run_id) indexed,
                              (SELECT count(*) FROM segment_embedding e WHERE e.ingestion_run_id=ir.run_id) embeddings
                       FROM document_revision r JOIN ingestion_run ir ON ir.revision_id=r.revision_id
                       WHERE r.canonical_document_id=:document_id ORDER BY ir.created_at DESC LIMIT 1"""
                    ),
                    {"document_id": accepted["document_id"]},
                )
                .mappings()
                .one()
            )
        store = S3ObjectStore(settings)
        object_exists = store.exists(
            object_key=row["object_key"], version_id=row["object_version_id"]
        )
        search = httpx.get(
            "http://127.0.0.1:8000/api/assets/hybrid-search",
            headers=headers,
            params={"q": marker, "security_id": "600276", "limit": 10},
            timeout=10,
        ).json()
        report = {
            "accepted": accepted,
            "job": snapshot,
            "lineage": dict(row),
            "object_version_exists": object_exists,
            "hybrid_search_hit": any(
                hit["document_id"] == accepted["document_id"] for hit in search
            ),
        }
        if not all(
            [
                object_exists,
                row["status"] == "succeeded",
                row["segment_count"] > 0,
                row["artifacts"] > 0,
                row["indexed"] > 0,
                row["embeddings"] > 0,
                report["hybrid_search_hit"],
            ]
        ):
            raise RuntimeError(json.dumps(report, ensure_ascii=False, default=str))
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    finally:
        probe.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
