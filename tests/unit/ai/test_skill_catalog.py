from __future__ import annotations

import pytest

from app.ai.prompts.templates import (
    EVENT_IMPACT,
    METRIC_EXPLAIN,
    REVIEW_DRAFT,
    THESIS_DRAFT,
    PromptTemplate,
)
from app.ai.skill_catalog import SkillDefinitionError, load_skill


@pytest.mark.parametrize(
    ("skill_key", "schema_name", "template"),
    [
        ("thesis-draft", "thesis_draft", THESIS_DRAFT),
        ("event-impact", "event_impact", EVENT_IMPACT),
        ("metric-explain", "metric_explain", METRIC_EXPLAIN),
        ("review-draft", "review_draft", REVIEW_DRAFT),
    ],
)
def test_skill_definition_drives_prompt_template(
    skill_key: str,
    schema_name: str,
    template: PromptTemplate,
) -> None:
    skill = load_skill(skill_key)

    assert skill.schema_name == schema_name
    assert "-v" in skill.version
    assert skill.path.name == "SKILL.md"
    assert template.version == skill.version
    assert template.system == skill.system
    assert template.instruction == skill.instruction


def test_unknown_skill_fails_without_resolving_a_dynamic_path() -> None:
    with pytest.raises(SkillDefinitionError, match="未知 AI Skill"):
        load_skill("../../.env")
