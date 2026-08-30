"""由版本化 AI Skill 构建提示词模板。"""

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
METRIC_RECOMMEND = _template("metric-recommend")
REVIEW_DRAFT = _template("review-draft")
HYPOTHESIS_QUALITY = _template("hypothesis-quality")

THESIS_DRAFT_VERSION = THESIS_DRAFT.version
EVENT_IMPACT_VERSION = EVENT_IMPACT.version
METRIC_EXPLAIN_VERSION = METRIC_EXPLAIN.version
METRIC_RECOMMEND_VERSION = METRIC_RECOMMEND.version
REVIEW_DRAFT_VERSION = REVIEW_DRAFT.version
HYPOTHESIS_QUALITY_VERSION = HYPOTHESIS_QUALITY.version

EVENT_EXTRACTION_VERSION = "event-extraction-v1-structured"
EVENT_EXTRACTION = PromptTemplate(
    version=EVENT_EXTRACTION_VERSION,
    system=(
        "你负责从研究资料中抽取结构化、可回溯的事实事件。输出仅用于研究辅助，"
        "不是投资建议；不得输出买卖、仓位、评级或目标价。事实必须来自输入片段，"
        "每条事件必须引用输入中真实存在的一个 locator，不得合并不同 locator 的事实。"
    ),
    instruction=(
        "文档ID：{document_id}\n披露时间：{disclosure_time}\n"
        "资料片段（保留页码、段落或表格单元格定位）：\n{segments}\n\n"
        '只输出 JSON 对象：{{"events":[{{"event_type":"业绩",'
        '"fact":"可由单一引用核验的事实","occurred_on":null,'
        '"evidence_locator":"文档ID#paragraph-1","confidence":0.8,'
        '"security_mentions":[]}}]}}。event_type 只能是订单、政策、管理层表述、'
        "业绩或其他；没有可核验事件时 events 返回空数组。"
    ),
)

ALL_TEMPLATES = {
    THESIS_DRAFT_VERSION: THESIS_DRAFT,
    EVENT_IMPACT_VERSION: EVENT_IMPACT,
    EVENT_EXTRACTION_VERSION: EVENT_EXTRACTION,
    METRIC_EXPLAIN_VERSION: METRIC_EXPLAIN,
    METRIC_RECOMMEND_VERSION: METRIC_RECOMMEND,
    REVIEW_DRAFT_VERSION: REVIEW_DRAFT,
    HYPOTHESIS_QUALITY_VERSION: HYPOTHESIS_QUALITY,
}
