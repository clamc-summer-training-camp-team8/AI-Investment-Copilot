from app.ai.prompts.templates import EVENT_EXTRACTION


def test_event_extraction_prompt_renders_json_example_as_literal() -> None:
    prompt = EVENT_EXTRACTION.render(
        document_id="DOC-1",
        disclosure_time="2026-08-29T00:00:00+08:00",
        segments="[DOC-1#paragraph-1] 测试事实",
    )

    assert '"events"' in prompt
    assert '"security_mentions":[]' in prompt
    assert "DOC-1#paragraph-1" in prompt
