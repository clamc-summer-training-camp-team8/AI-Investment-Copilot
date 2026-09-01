import json
from pathlib import Path

from jsonschema import Draft202012Validator


def test_knowledge_answer_schema_accepts_grounded_answer() -> None:
    schema = json.loads(
        Path("contracts/ai/knowledge_answer.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(
        {
            "answer_status": "supported",
            "answer": "销量增长。[S1]",
            "inferences": [],
            "citations": ["DOC-1#paragraph-1"],
            "requires_human_review": True,
            "model_version": "local-rule-v1",
            "prompt_version": "knowledge-answer-v1-grounded-citations",
            "generated_at": "2026-08-31T00:00:00Z",
            "ai_status": "候选",
        }
    )
