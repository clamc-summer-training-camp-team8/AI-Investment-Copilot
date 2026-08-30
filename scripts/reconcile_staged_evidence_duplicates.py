"""Remove exact duplicate staged evidence created by an earlier importer idempotency key."""

from __future__ import annotations

import argparse
from collections import defaultdict

from sqlalchemy import select

from app.db.models.core import Evidence
from app.db.session import session_scope


def _business_key(row: Evidence) -> tuple[str | None, ...]:
    return (
        row.source_url,
        row.hypothesis_id,
        row.direction,
        row.fact_excerpt,
        row.source_document_title,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="实际删除重复项；默认仅报告")
    args = parser.parse_args()

    with session_scope() as session:
        rows = session.scalars(
            select(Evidence).where(Evidence.model_version == "gpt-5.6-terra-offline")
        ).all()
        groups: dict[tuple[str | None, ...], list[Evidence]] = defaultdict(list)
        for row in rows:
            groups[_business_key(row)].append(row)
        duplicate_groups = [group for group in groups.values() if len(group) > 1]
        redundant = [
            row
            for group in duplicate_groups
            for row in sorted(group, key=lambda item: (item.created_at, item.evidence_id))[1:]
        ]
        print(
            {
                "staged_evidence": len(rows),
                "duplicate_groups": len(duplicate_groups),
                "redundant_rows": len(redundant),
                "mode": "apply" if args.apply else "dry_run",
            }
        )
        if args.apply:
            for row in redundant:
                session.delete(row)


if __name__ == "__main__":
    main()
