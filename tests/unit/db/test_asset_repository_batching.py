from unittest.mock import MagicMock

from sqlalchemy.dialects import postgresql

from app.core.domain import IngestionArtifactRecord
from app.db.repositories import assets as assets_repository
from app.db.repositories.assets import SqlAssetRepo


def _segments(count: int) -> list[IngestionArtifactRecord]:
    return [
        IngestionArtifactRecord(
            run_id="IRUN-test",
            artifact_type="segment",
            artifact_key=f"DOC-test#paragraph-{index}",
            payload={"content": f"segment {index}"},
            content_hash=f"hash-{index}",
        )
        for index in range(1, count + 1)
    ]


def test_add_artifacts_batches_multirow_upserts(monkeypatch) -> None:
    monkeypatch.setattr(assets_repository, "_BULK_WRITE_BATCH_SIZE", 2)
    session = MagicMock()

    SqlAssetRepo(session).add_artifacts(_segments(5))

    assert session.execute.call_count == 3
    assert session.flush.call_count == 1
    parameter_counts = [
        len(call.args[0].compile(dialect=postgresql.dialect()).params)
        for call in session.execute.call_args_list
    ]
    assert parameter_counts == [10, 10, 5]


def test_index_artifacts_batches_segment_lookup_and_upsert(monkeypatch) -> None:
    monkeypatch.setattr(assets_repository, "_BULK_WRITE_BATCH_SIZE", 2)
    records = _segments(5)
    session = MagicMock()
    session.execute.side_effect = [
        [(records[0].artifact_key, 1), (records[1].artifact_key, 2)],
        [(records[2].artifact_key, 3), (records[3].artifact_key, 4)],
        [(records[4].artifact_key, 5)],
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    ]

    SqlAssetRepo(session).index_artifacts(
        run_id="IRUN-test",
        document_id="DOC-test",
        visibility_label="内部",
        records=records,
    )

    assert session.execute.call_count == 7
    assert session.flush.call_count == 1
    insert_calls = session.execute.call_args_list[3:6]
    parameter_counts = [
        len(call.args[0].compile(dialect=postgresql.dialect()).params) for call in insert_calls
    ]
    assert parameter_counts == [14, 14, 7]


def test_rebuild_search_index_batches_documents(monkeypatch) -> None:
    monkeypatch.setattr(assets_repository, "_SEARCH_REBUILD_DOCUMENT_BATCH_SIZE", 2)
    session = MagicMock()
    session.scalars.return_value = ["DOC-1", "DOC-2", "DOC-3"]
    session.scalar.return_value = 9

    count = SqlAssetRepo(session).rebuild_search_index()

    assert count == 9
    assert session.execute.call_count == 5
    truncate = str(session.execute.call_args_list[0].args[0])
    assert truncate == "TRUNCATE TABLE segment_search_index CASCADE"
    parameters = [call.args[1]["document_ids"] for call in session.execute.call_args_list[1:]]
    assert parameters == [
        ["DOC-1", "DOC-2"],
        ["DOC-1", "DOC-2"],
        ["DOC-3"],
        ["DOC-3"],
    ]
