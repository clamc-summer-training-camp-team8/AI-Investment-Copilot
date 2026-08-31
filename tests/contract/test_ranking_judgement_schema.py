from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


def test_ranking_judgement_contract_accepts_structured_result() -> None:
    schema = json.loads(
        Path("contracts/ai/ranking_judgement.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(
        {
            "model_version": "ranking-judge-v1",
            "prompt_version": "ranking-judge-prompt-v1",
            "generated_at": "2026-08-30T10:00:00Z",
            "ai_status": "候选",
            "verdict": "accept",
            "confidence": 0.9,
            "ranking": [
                {
                    "object_id": "DOC-1#paragraph-1",
                    "rank": 1,
                    "score": 0.92,
                    "reason_codes": ["CORE_DRIVER"],
                    "citation_locators": ["DOC-1#paragraph-1"],
                    "issues": [],
                }
            ],
            "removed_candidates": [],
            "global_issues": [],
            "requires_review": False,
        }
    )
