"""Repair rebuildable search rows whose canonical segment lineage is incomplete.

Older duplicate-ingestion runs can contain a pre-canonical document id in their artifact
locator.  This command only remaps such a row when the target document has the same locator
suffix and byte-identical segment text.  It also fills missing ``segment_id`` values for exact
document/locator matches.  Ambiguous, conflicting, or content-changing mappings abort the whole
transaction.
"""

from __future__ import annotations

import json

from sqlalchemy import text

from app.db.session import session_scope


def reconcile() -> dict[str, int]:
    with session_scope() as session:
        mismatched = int(
            session.scalar(
                text(
                    """SELECT count(*) FROM segment_search_index i
                       WHERE i.locator NOT LIKE i.document_id || '#%'"""
                )
            )
            or 0
        )
        unresolvable = int(
            session.scalar(
                text(
                    """SELECT count(*) FROM segment_search_index i
                       WHERE i.locator NOT LIKE i.document_id || '#%'
                         AND NOT EXISTS (
                           SELECT 1 FROM document_segment s
                           WHERE s.document_id=i.document_id
                             AND s.locator=i.document_id ||
                                 substring(i.locator from position('#' in i.locator))
                             AND s.content=i.content
                         )"""
                )
            )
            or 0
        )
        conflicts = int(
            session.scalar(
                text(
                    """SELECT count(*) FROM segment_search_index i
                       WHERE i.locator NOT LIKE i.document_id || '#%'
                         AND EXISTS (
                           SELECT 1 FROM segment_search_index other
                           WHERE other.index_id<>i.index_id
                             AND other.document_id=i.document_id
                             AND other.locator=i.document_id ||
                                 substring(i.locator from position('#' in i.locator))
                         )"""
                )
            )
            or 0
        )
        if unresolvable or conflicts:
            raise RuntimeError(
                f"搜索血缘存在不可安全映射记录：unresolvable={unresolvable}, "
                f"conflicts={conflicts}"
            )

        remap_result = session.execute(
            text(
                """UPDATE segment_search_index i
                   SET locator=s.locator, segment_id=s.id, content=s.content,
                       search_vector=to_tsvector('simple',coalesce(s.content,''))
                   FROM document_segment s
                   WHERE i.locator NOT LIKE i.document_id || '#%'
                     AND s.document_id=i.document_id
                     AND s.locator=i.document_id ||
                         substring(i.locator from position('#' in i.locator))
                     AND s.content=i.content"""
            )
        )
        remapped = int(getattr(remap_result, "rowcount", 0) or 0)
        link_result = session.execute(
            text(
                """UPDATE segment_search_index i
                   SET segment_id=s.id
                   FROM document_segment s
                   WHERE i.segment_id IS NULL
                     AND s.document_id=i.document_id
                     AND s.locator=i.locator"""
            )
        )
        linked = int(getattr(link_result, "rowcount", 0) or 0)
        embedding_result = session.execute(
            text(
                """UPDATE segment_embedding e
                   SET document_id=i.document_id, locator=i.locator
                   FROM segment_search_index i
                   WHERE i.index_id=e.index_id
                     AND (e.document_id<>i.document_id OR e.locator<>i.locator)"""
            )
        )
        embeddings_linked = int(getattr(embedding_result, "rowcount", 0) or 0)
        remaining_mismatch = int(
            session.scalar(
                text(
                    """SELECT count(*) FROM segment_search_index i
                       WHERE i.locator NOT LIKE i.document_id || '#%'"""
                )
            )
            or 0
        )
        remaining_unlinked = int(
            session.scalar(
                text("SELECT count(*) FROM segment_search_index WHERE segment_id IS NULL")
            )
            or 0
        )
        if remaining_mismatch or remaining_unlinked:
            raise RuntimeError(
                f"搜索血缘对账未收敛：mismatch={remaining_mismatch}, "
                f"unlinked={remaining_unlinked}"
            )
        return {
            "mismatched_before": mismatched,
            "locators_remapped": remapped,
            "segment_ids_linked": linked,
            "embedding_locators_linked": embeddings_linked,
            "mismatched_after": remaining_mismatch,
            "unlinked_after": remaining_unlinked,
        }


def main() -> None:
    print(json.dumps(reconcile(), ensure_ascii=False))


if __name__ == "__main__":
    main()
