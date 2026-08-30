"""Attach reviewed, page-addressable primary-source excerpts to existing documents.

This intentionally adds body slices instead of overwriting the compact fact sheet
segment created by ``import_staged_official_sources``.  The fact sheet remains a
traceable evidence record; these slices make the underlying disclosure retrievable.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from app.core.config import PROJECT_ROOT
from app.db.models.core import Document, DocumentSegment
from app.db.session import session_scope


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=PROJECT_ROOT / "analytics" / "staging" / "p1-geely-reviewed-body-chunks-20260824.json",
    )
    parser.add_argument("--confirm-reviewed-excerpts", action="store_true")
    args = parser.parse_args()
    if not args.confirm_reviewed_excerpts:
        parser.error("该命令会写入正文切片；请显式传入 --confirm-reviewed-excerpts")

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if payload.get("status") != "staged_requires_human_review":
        raise SystemExit("只允许导入 staged_requires_human_review 状态的数据包")

    inserted = skipped = 0
    with session_scope() as session:
        for item in payload["chunks"]:
            source_url = str(item["source_url"])
            document = session.scalar(select(Document).where(Document.raw_path == source_url))
            if document is None:
                raise ValueError(f"未找到已入库来源文档：{source_url}")
            locator = f"{document.document_id}#body-{item['chunk_key']}"
            if session.scalar(select(DocumentSegment).where(DocumentSegment.locator == locator)):
                skipped += 1
                continue
            session.add(
                DocumentSegment(
                    document_id=document.document_id,
                    locator=locator,
                    ordinal=int(item["ordinal"]),
                    page=item.get("page"),
                    content=item["content"],
                    content_kind="paragraph",
                    extraction_method="reviewed_body",
                    confidence=item.get("confidence", 0.95),
                )
            )
            inserted += 1
    print(json.dumps({"segments_inserted": inserted, "segments_skipped": skipped}, ensure_ascii=False))


if __name__ == "__main__":
    main()
