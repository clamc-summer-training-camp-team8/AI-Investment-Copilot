"""提示词模板，带版本号。

提示词改动视为发布行为，需可灰度可回滚（FR-A-002）。改模板必须同时改版本号，
否则历史结论无法复现——`signal.prompt_version` 存的是这里的版本字符串。

模板里**禁止要求模型计算关键数值**（PRD 10.5 第二条）。预期差、同比环比、趋势、
同业分位一律由 app/calc 算，模型只解释结果。评审会查这一点。
"""

from __future__ import annotations

from dataclasses import dataclass

THESIS_DRAFT_VERSION = "thesis-draft-v3-deepseek-json-ref-null"
EVENT_IMPACT_VERSION = "event-impact-v2-mentor-ruling"
EVENT_EXTRACTION_VERSION = "event-extraction-v1-structured"
METRIC_EXPLAIN_VERSION = "metric-validation-v1"


@dataclass(frozen=True)
class PromptTemplate:
    version: str
    system: str
    instruction: str

    def render(self, **kwargs: str) -> str:
        return self.instruction.format(**kwargs)


_NO_TRADE_ADVICE = (
    "你输出的是研究辅助信息，不是投资建议。" "禁止输出买入、卖出、增持、减持、评级或目标价。"
)

_CITATION_RULE = (
    "事实类结论必须给出引用，格式 {document_id}#paragraph-{n}，且只能引用输入中出现的段落。"
    "无法引用的内容必须标记为推断或不确定，不得作为事实输出。"
)

_THESIS_JSON_SHAPE = """
只输出一个 JSON 对象，不要使用 Markdown 代码块，不要增加下列结构之外的字段：
{
  "title": "不超过40字的标题",
  "direction": null,
  "core_view": "不超过200字的核心观点",
  "hypotheses": [
    {
      "statement": "可证伪假设",
      "hypothesis_type": "经营",
      "importance": "核心",
      "metric_suggestions": [{"metric_name": "指标名称", "unit": "单位", "observation_frequency": "季度", "rationale": "观察目的"}],
      "evidence_locator": "输入中的文档ID#paragraph-1"
    },
    {
      "statement": "第二条可证伪假设",
      "hypothesis_type": "盈利",
      "importance": "辅助",
      "metric_suggestions": [],
      "evidence_locator": null
    }
  ],
  "risks": [{"statement": "风险", "evidence_locator": null}],
  "invalidation_suggestions": [{"statement": "失效条件建议", "hypothesis_ref": null, "require_all": true, "consecutive_periods": 2}],
  "citations": [],
  "unsupported_claims": [],
  "confidence": 0.8
}
草稿阶段尚未分配 hypothesis_id，因此 hypothesis_ref 必须为 null，禁止填写数组索引或序号。
""".strip()

_EVENT_JSON_SHAPE = """
只输出一个 JSON 对象，不要使用 Markdown 代码块，不要增加下列结构之外的字段：
{
  "relevance": "相关",
  "event": {"fact": "可由输入引用支持的事实", "inference": "与事实分开的推断"},
  "signal": {
    "direction": "正向",
    "impact_direction": "支持",
    "strength": 0.8,
    "confidence": 0.8,
    "horizon": "中期",
    "rationale": "相对具体假设的判断理由",
    "transmission_path": "事件到可观测指标再到假设的路径",
    "suggested_tracking": ["后续观察项"]
  }
}
枚举必须严格使用：relevance=相关/不相关/待定；direction=正向/负向/中性/不确定；
impact_direction=支持/冲突/中性/无关；horizon=短期/中期/长期/null。
""".strip()

_EVENT_EXTRACTION_JSON_SHAPE = """
只输出 JSON 对象：
{"events":[{"event_type":"业绩","fact":"可由单一引用直接核验的事实", "occurred_on":null,
"evidence_locator":"输入中的文档ID#paragraph-1","confidence":0.8,"security_mentions":["证券代码或公司名"]}]}
event_type 只能是订单/政策/管理层表述/业绩/其他。没有可核验事件时 events 返回空数组。
每条事件必须引用输入中真实存在的一个 locator；禁止合并来自不同 locator 的事实。
""".strip()

_MENTOR_EVENT_RULES = (
    "业务裁决 mentor-ruling-v1-20260811：影响方向只相对于给定假设及其可观测指标判断。"
    "无关表示不进入证据链；中性表示相关但方向不明。高频过程公告、程式化文件、"
    "I/II期进展和无金额框架协议判无关；NDA受理、方向取决于标的的融资或投资判中性；"
    "获批上市、III期达到主要终点、有明确金额的订单或许可判支持；研发失败、撤回、"
    "III期未达终点判冲突。无法从正文确认金额或决定性节点时采取保守方向。"
)

THESIS_DRAFT = PromptTemplate(
    version=THESIS_DRAFT_VERSION,
    system=(
        "你是投研助手，负责把研究员的观点和资料整理成结构化的投资逻辑草稿。"
        f"{_NO_TRADE_ADVICE}{_CITATION_RULE}"
        "不要填写研究员的预期值和正式阈值——这两项只能由研究员本人填写。"
        f"{_THESIS_JSON_SHAPE}"
    ),
    instruction=(
        "投资对象：{security}\n"
        "研究员观点：{view}\n"
        "资料正文（带段落定位）：\n{segments}\n\n"
        "输出 JSON，包含标题（≤40字）、核心观点（≤200字）、2至5条关键假设"
        "（至少1条核心）、每条假设的指标建议、风险、失效条件建议和引用。"
        "指标建议只给口径和观察目的，不要给预期值。"
    ),
)

EVENT_IMPACT = PromptTemplate(
    version=EVENT_IMPACT_VERSION,
    system=(
        "你负责判断一条新事件对已有投资假设的影响。"
        f"{_NO_TRADE_ADVICE}{_CITATION_RULE}"
        "影响方向是相对于具体假设的，不是股价方向，也不是通用情绪极性。"
        f"{_MENTOR_EVENT_RULES}{_EVENT_JSON_SHAPE}"
    ),
    instruction=(
        "事件正文：{event}\n"
        "披露时间：{disclosure_time}\n"
        "候选逻辑与假设：\n{candidates}\n"
        "已有预期与证据：\n{context}\n\n"
        "输出 JSON，包含相关性、目标假设、影响方向、强度、事实摘要、传导路径、"
        "建议跟踪项和引用。区分事实与推断。置信度不足时如实给低分，不要为了"
        "给出结论而抬高置信度。"
    ),
)

EVENT_EXTRACTION = PromptTemplate(
    version=EVENT_EXTRACTION_VERSION,
    system=(
        "你负责从研究资料中抽取结构化、可回溯的事实事件。"
        f"{_NO_TRADE_ADVICE}{_CITATION_RULE}{_EVENT_EXTRACTION_JSON_SHAPE}"
    ),
    instruction=(
        "文档ID：{document_id}\n披露时间：{disclosure_time}\n"
        "资料片段（保留页码、段落或表格单元格定位）：\n{segments}\n\n"
        "抽取订单、政策、管理层表述、业绩和其他重大可核验事件。事实与推断分离；"
        "仅标题、程式化声明和无法引用的内容不要产出事件。"
    ),
)

METRIC_EXPLAIN = PromptTemplate(
    version=METRIC_EXPLAIN_VERSION,
    system=(
        "你负责解释确定性计算的结果与投资假设的关系。"
        f"{_NO_TRADE_ADVICE}"
        "输入中的数值已由程序算出，你不得重新计算、修正或推算任何数值。"
    ),
    instruction=(
        "假设：{hypothesis}\n"
        "程序计算结果（口径已固定）：\n{calc_result}\n\n"
        "用两三句话说明这个结果对假设意味着什么，以及需要继续观察什么。"
        "不要给出新的数字。"
    ),
)

ALL_TEMPLATES = {
    THESIS_DRAFT_VERSION: THESIS_DRAFT,
    EVENT_IMPACT_VERSION: EVENT_IMPACT,
    EVENT_EXTRACTION_VERSION: EVENT_EXTRACTION,
    METRIC_EXPLAIN_VERSION: METRIC_EXPLAIN,
}
