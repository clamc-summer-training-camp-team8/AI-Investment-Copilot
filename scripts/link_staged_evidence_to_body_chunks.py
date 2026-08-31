"""Move staged evidence locators from fact-sheet summaries to reviewed body slices."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from app.core.config import PROJECT_ROOT
from app.db.models.core import Document, DocumentSegment, Evidence
from app.db.session import session_scope


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=PROJECT_ROOT
        / "analytics"
        / "staging"
        / "p1-geely-evidence-body-locator-map-20260824.json",
    )
    parser.add_argument("--confirm-locator-update", action="store_true")
    args = parser.parse_args()
    if not args.confirm_locator_update:
        parser.error("该命令会更新候选证据定位；请显式传入 --confirm-locator-update")
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if payload.get("status") != "staged_requires_human_review":
        raise SystemExit("只允许导入 staged_requires_human_review 状态的数据包")

    updated = 0
    with session_scope() as session:
        for item in payload["mappings"]:
            document = session.scalar(
                select(Document).where(Document.raw_path == item["source_url"])
            )
            if document is None:
                raise ValueError(f"未找到来源文档：{item['source_url']}")
            locator = f"{document.document_id}#body-{item['chunk_key']}"
            if (
                session.scalar(select(DocumentSegment).where(DocumentSegment.locator == locator))
                is None
            ):
                raise ValueError(f"未找到正文切片：{locator}")
            evidences = session.scalars(
                select(Evidence).where(
                    Evidence.source_url == item["source_url"],
                    Evidence.direction == item["direction"],
                    Evidence.confirmation_status == "待确认",
                )
            ).all()
            for evidence in evidences:
                if evidence.evidence_locator != locator:
                    evidence.evidence_locator = locator
                    updated += 1
    print(json.dumps({"evidence_locators_updated": updated}, ensure_ascii=False))


if __name__ == "__main__":
    main()
