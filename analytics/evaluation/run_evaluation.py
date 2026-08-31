"""AI 评测：关键词基线 vs AI，按样本内/样本外分别报告（DA-AC-05）。

金标口径：采用标注者 A 与 B **一致**的样本作为金标，不一致的 325 条进裁决队列、
不进评测。理由是这些样本连规则本身都没定清楚，用它们算准确率得到的是噪音。
这个取舍会让评测集偏易——必须在报告里写明，这是选择偏差的一种形式。

用法：
    python -m analytics.evaluation.run_evaluation
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime

from analytics.evaluation.baseline import predict as baseline_predict
from analytics.evaluation.candidate_v2 import predict as candidate_predict
from analytics.evaluation.metrics import LinkMetrics, evaluate_links
from analytics.pipelines.annotate_events import (
    ANNOTATION_VERSION,
    CATEGORY_RULES,
    RULING_VERSION,
    mentor_ruling,
)
from analytics.pipelines.universe import INDUSTRIES
from app.ai.providers.local import guess_hypothesis_type, judge_impact
from app.core.config import PROJECT_ROOT, Settings
from app.core.enums import ImpactDirection

DATASET_DIR = PROJECT_ROOT / "real_data" / "dataset"
REPORT_DIR = PROJECT_ROOT / "real_data" / "reports"


@dataclass
class Row:
    event_id: str
    company: str
    industry: str
    title: str
    category: str
    split: str
    truth_hypothesis: str
    truth_direction: str
    adjudicated: bool


def adjudicate(
    a_hypothesis: str,
    a_direction: str,
    b_hypothesis: str,
    b_direction: str,
    title: str = "",
) -> tuple[str, str]:
    """裁决规则：两名标注者冲突时的确定性处理（说明书 12 要求提交业务裁决）。

    真正的裁决应由业务导师做（GAP-004）。在导师确认前用一条**公开写明的保守规则**
    占位，而不是把冲突样本丢掉：

    - 关联与否有分歧 → 以「有关联」为准，保留样本，方向取中性。
      丢掉分歧样本会把评测集变简单（本轮实测：丢弃后 329 条方向明确样本只剩 5 条），
      得到的准确率虚高。
    - 方向有分歧 → 取中性。中性表示「事件相关但方向需人工判断」，这与产品设计一致：
      方向不明的证据本来就该进人工队列，不该由机器拍一个方向。

    这条规则会系统性偏向中性，压低方向一致率——是保守方向的偏差，报告里写明。
    """
    ruled = mentor_ruling(title) if title else None
    if ruled is not None:
        return ruled

    hypothesis = a_hypothesis or b_hypothesis
    if not hypothesis:
        return "", ImpactDirection.IRRELEVANT.value
    if a_direction == b_direction:
        return hypothesis, a_direction
    return hypothesis, ImpactDirection.NEUTRAL.value


def load_gold() -> list[Row]:
    """读入金标。

    保留**全部**样本：一致的直接采用，不一致的按 `adjudicate` 裁决后采用。
    """
    path = DATASET_DIR / "events.csv"
    rows: list[Row] = []
    with path.open(encoding="utf-8") as fh:
        for record in csv.DictReader(fh):
            agreed = record["agreed"] == "True"
            hypothesis, direction = adjudicate(
                record["annotator_a_hypothesis"],
                record["annotator_a_direction"],
                record["annotator_b_hypothesis"],
                record["annotator_b_direction"],
                record["title"],
            )
            rows.append(
                Row(
                    event_id=record["event_id"],
                    company=record["company"],
                    industry=record.get("industry", ""),
                    title=record["title"],
                    category=record["category"],
                    split=record["split"],
                    truth_hypothesis=hypothesis,
                    truth_direction=direction,
                    adjudicated=not agreed,
                )
            )
    return rows


# local 提供者的 guess_hypothesis_type 输出行业/经营/盈利三分类，与本轮的
# H1/H2/H3 不是同一套编码。这里声明一张映射表把它对齐到假设编号。
#
# 这张表**不使用**标注侧的 CATEGORY_TO_HYPOTHESIS，也不看公告的监管类型，只接受
# AI 从标题文本推断出的类型。两条信息路径必须分开，否则 AI 等于抄标注答案，
# 关联准确率会恒等于 100%，评测不测量任何东西。
#
# 注意 local 的词表里没有「产能/扩张」这一类概念，因此 H3 必然召回不到。
# 这是真实缺口，不是实现缺陷，报告里如实披露。
AI_TYPE_TO_HYPOTHESIS: dict[str, str] = {
    "行业": "H1-需求与出货",
    "经营": "H1-需求与出货",
    "盈利": "H2-盈利质量",
}


def ai_predict(row: Row) -> tuple[str, str]:
    """AI 预测：只看标题文本，走 `app.ai.providers.local` 的现成规则。

    **不为这个评测集调整词表。** 调了就是拿测试集调参（说明书 10.4 参数过拟合），
    得到的数字不可信。
    """
    ai_type = guess_hypothesis_type(row.title)
    hypothesis = AI_TYPE_TO_HYPOTHESIS.get(ai_type, "")
    if not hypothesis:
        return "", ImpactDirection.IRRELEVANT.value
    return hypothesis, judge_impact(row.title).impact_direction.value


def _vocab_overlap() -> float:
    """v2 词表与金标词表的重合度。

    这个数字必须出现在报告里。它是解读准确率的前提：重合度越高，准确率越接近
    「规则复现规则」而不是「模型理解业务」。自己算出来写清楚，比等别人质疑要好。
    """
    from analytics.evaluation.candidate_v2 import _TOPIC_PATTERNS

    gold = {term for _, pattern in CATEGORY_RULES for term in pattern.split("|")}
    v2 = {term for _, pattern in _TOPIC_PATTERNS for term in pattern.pattern.split("|")}
    if not v2:
        return 0.0
    return len(gold & v2) / len(v2)


def baseline_pair(row: Row) -> tuple[str, str]:
    output = baseline_predict(row.title)
    return output.hypothesis, output.direction


def candidate_pair(row: Row) -> tuple[str, str]:
    output = candidate_predict(row.title)
    return output.hypothesis, output.direction


def evaluate(rows: list[Row]) -> dict[str, LinkMetrics]:
    truth = [(r.truth_hypothesis, r.truth_direction) for r in rows]
    return {
        "keyword_baseline": evaluate_links([baseline_pair(r) for r in rows], truth),
        "ai_local_v1": evaluate_links([ai_predict(r) for r in rows], truth),
        "candidate_v2": evaluate_links([candidate_pair(r) for r in rows], truth),
    }


def _report_block(title: str, metrics: dict[str, LinkMetrics]) -> list[str]:
    lines = [f"## {title}", ""]
    for name, result in metrics.items():
        lines.append(f"### {name}")
        lines.extend(f"- {line}" for line in result.render())
        lines.append("")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    rows = load_gold()
    in_sample = [r for r in rows if r.split == "in_sample"]
    out_sample = [r for r in rows if r.split == "out_of_sample"]

    settings = Settings()
    adjudicated = sum(1 for r in rows if r.adjudicated)
    linked = sum(1 for r in rows if r.truth_hypothesis)
    header = [
        "# AI 评测报告",
        "",
        f"生成时间: {datetime.now().astimezone().isoformat()}",
        f"模型版本: {settings.llm_model_version} (provider={settings.llm_provider})",
        f"标注版本: {ANNOTATION_VERSION} / {RULING_VERSION}",
        "数据版本: cninfo-announcement-v2",
        "基线: 关键词法（analytics/evaluation/baseline.py）",
        f"研究范围: {len(INDUSTRIES)} 个行业 × 3 家公司（{'、'.join(INDUSTRIES)}）",
        "",
        f"金标样本: {len(rows)} 条（全部样本，含裁决后的 {adjudicated} 条分歧样本）",
        f"其中影响核心假设: {linked} 条",
        f"样本内: {len(in_sample)} 条 / 样本外: {len(out_sample)} 条（按 2025-10-01 时间切分）",
        "",
        "## 结论适用范围（先读这一节再看数字）",
        "",
        "**本轮证明的是评测链路可运行、口径可复算，不构成 AI 能力结论。**",
        "",
        (
            "1. 本报告仍以程序化预标注 + 导师规则裁决评估旧规则模型，不能替代独立金标。"
            "59 条独立盲标已完成，结论见 `dataset/blind_annotation_result/REPORT.md`："
            "筛选精度较高，但方向判断一致率不足。"
        ),
        f"2. `candidate_v2` 的词表与金标词表重合 {_vocab_overlap():.0%}。",
        "   其准确率有相当部分来自「规则复现规则」，**不能读作 AI 能力**。",
        "   要得到可信数字，必须有独立于抽取规则的人工金标。这是本轮最重要的结论。",
        "3. `ai_local_v1` 是 `app/ai/providers/local.py` 的现网规则，未做任何改动。",
        "   它的词表按储能行业研报正文措辞写（装机/需求/毛利率），既不匹配公告标题，",
        "   也不覆盖半导体与医药的措辞，因此召回率极低。这是真实能力缺口，不是实现缺陷。",
        "4. `candidate_v2` 的词表**只用样本内数据构造**，定稿后未依据样本外结果调整。",
        "   样本外那一次即最终成绩（说明书 10.2 第 2、4 步）。",
        "5. 裁决规则系统性偏向中性，会压低本报告中的方向一致率。",
        "6. 跨行业后金标的方向一致性按行业差异很大（医药 kappa 0.50、半导体 0.69、",
        "   汽车 0.96）。医药低是因为「拿到临床批件算不算支持需求」这类问题本身没有",
        "   共识，需要业务裁决，不是标注者失误。",
        "",
    ]

    sections: list[str] = list(header)
    for label, subset in (("样本内", in_sample), ("样本外", out_sample), ("全样本", rows)):
        sections.extend(_report_block(label, evaluate(subset)))

    # 分行业看样本外表现。总数会掩盖单行业失效：同一套规则在三个行业上的
    # 召回与方向一致率差异很大，混在一起报只会得到一个没人能用的平均数。
    sections.extend(["## 分行业（样本外）", ""])
    for industry in INDUSTRIES:
        subset = [r for r in out_sample if r.industry == industry]
        if not subset:
            sections.extend([f"### {industry}", "- 样本外无样本", ""])
            continue
        sections.append(f"### {industry}（{len(subset)} 条）")
        for name, result in evaluate(subset).items():
            sections.append(f"- **{name}**：" + "；".join(result.render()))
        sections.append("")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    target = REPORT_DIR / "evaluation_report.md"
    target.write_text("\n".join(sections), encoding="utf-8")

    print("\n".join(sections))
    print(f"→ {target}")


if __name__ == "__main__":
    main()
