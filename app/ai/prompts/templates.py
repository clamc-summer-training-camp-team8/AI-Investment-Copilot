"""由版本化 AI Skill 构建的提示词模板。"""

from __future__ import annotations

from dataclasses import dataclass

from app.ai.skill_catalog import load_skill


@dataclass(frozen=True)
class PromptTemplate:
    version: str
    system: str
    instruction: str

    def render(self, **kwargs: str) -> str:
        return self.instruction.format(**kwargs)


def _template(skill_key: str) -> PromptTemplate:
    skill = load_skill(skill_key)
    return PromptTemplate(
        version=skill.version,
        system=skill.system,
        instruction=skill.instruction,
    )


THESIS_DRAFT = _template("thesis-draft")
EVENT_IMPACT = _template("event-impact")
METRIC_EXPLAIN = _template("metric-explain")
REVIEW_DRAFT = _template("review-draft")

THESIS_DRAFT_VERSION = THESIS_DRAFT.version
EVENT_IMPACT_VERSION = EVENT_IMPACT.version
METRIC_EXPLAIN_VERSION = METRIC_EXPLAIN.version
REVIEW_DRAFT_VERSION = REVIEW_DRAFT.version

ALL_TEMPLATES = {
    THESIS_DRAFT_VERSION: THESIS_DRAFT,
    EVENT_IMPACT_VERSION: EVENT_IMPACT,
    METRIC_EXPLAIN_VERSION: METRIC_EXPLAIN,
    REVIEW_DRAFT_VERSION: REVIEW_DRAFT,
}
