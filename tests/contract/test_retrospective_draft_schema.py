from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


def test_retrospective_draft_schema_is_valid_and_human_gated() -> None:
    schema = json.loads(
        Path("contracts/ai/retrospective_draft.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["requires_human_review"]["const"] is True
    source_pattern = schema["properties"]["citations"]["items"]["pattern"]
    assert source_pattern.startswith("^RCS-")
