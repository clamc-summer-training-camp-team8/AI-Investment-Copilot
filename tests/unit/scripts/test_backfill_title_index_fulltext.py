from decimal import Decimal
from unittest.mock import MagicMock, patch

from sqlalchemy.exc import OperationalError

from app.ingest.segmentation import Segment
from scripts import backfill_title_index_fulltext as backfill


def test_remap_segments_starts_after_preserved_locator_and_keeps_metadata() -> None:
    source = [
        Segment(
            document_id="DOC-1",
            locator="DOC-1#paragraph-1",
            ordinal=1,
            content="正文",
            page=3,
            content_kind="table_row",
            extraction_method="ocr",
            table_index=2,
            row_index=4,
            cell_range="A4:C4",
            confidence=Decimal("0.9876"),
        )
    ]

    remapped = backfill.remap_segments("DOC-1", source, after_ordinal=7)

    assert remapped == [
        Segment(
            document_id="DOC-1",
            locator="DOC-1#paragraph-8",
            ordinal=8,
            content="正文",
            page=3,
            content_kind="table_row",
            extraction_method="ocr",
            table_index=2,
            row_index=4,
            cell_range="A4:C4",
            confidence=Decimal("0.9876"),
        )
    ]


def test_remap_segments_uses_contiguous_ordinals_even_when_source_is_sparse() -> None:
    source = [
        Segment("DOC-2", "old-2", 2, "第一段"),
        Segment("DOC-2", "old-9", 9, "第二段"),
    ]

    remapped = backfill.remap_segments("DOC-2", source, after_ordinal=1)

    assert [item.locator for item in remapped] == [
        "DOC-2#paragraph-2",
        "DOC-2#paragraph-3",
    ]


def test_persist_retries_after_transient_database_disconnect() -> None:
    expected = backfill.ItemOutcome("DOC-1", "succeeded")
    disconnect = OperationalError(None, None, RuntimeError("connection reset"))

    with (
        patch.object(backfill, "_persist", side_effect=[disconnect, expected]) as persist,
        patch.object(backfill.engine, "dispose") as dispose,
        patch.object(backfill.time, "sleep") as sleep,
    ):
        actual = backfill._persist_with_retry(MagicMock())

    assert actual is expected
    assert persist.call_count == 2
    dispose.assert_called_once_with()
    sleep.assert_called_once_with(2)
