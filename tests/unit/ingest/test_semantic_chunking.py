from app.ingest.semantic_chunking import semantic_chunks


def test_semantic_chunks_append_stable_locators_and_keep_sentences() -> None:
    text = "收入同比增长20%。" * 30 + "\n\n毛利率保持稳定。" * 20

    chunks = semantic_chunks("DOC-1", text, max_chars=120, min_chars=20)

    assert len(chunks) > 1
    assert [item.ordinal for item in chunks] == list(range(1, len(chunks) + 1))
    assert chunks[0].locator == "DOC-1#paragraph-1"
    assert all(len(item.content) <= 120 for item in chunks)
    assert all(item.content_kind == "semantic" for item in chunks)
