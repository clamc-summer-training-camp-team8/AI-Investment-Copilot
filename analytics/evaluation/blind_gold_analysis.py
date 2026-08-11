"""用独立盲标金标评测现行标注管道。

这是第一次**不含循环**的评测：金标由业务方独立标注，不复现 `annotate_events.py`
的任何规则或词表。此前所有准确率数字都是"规则复现规则"，不能读作能力。

三个指标分开算，因为它们指向完全不同的改进方向：

| 指标 | 问的问题 | 瓶颈时该改什么 |
| --- | --- | --- |
| 筛选（精确率/召回率） | 该不该进证据链 | 类型映射与裁决层 |
| 方向（一致率） | 进了之后是什么方向 | 方向判定依据（标题 vs 正文） |
| kappa | 标注规则是否清晰 | 规则文档与培训 |

`annotation_stats.json` 里的 `direction_kappa = 1.0` 不能用来回答第三个问题：
它衡量的是两套程序化规则之间的相关性。本模块算的 kappa 才有诊断意义。

用法：
    python -m analytics.evaluation.blind_gold_analysis
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime

from app.core.config import PROJECT_ROOT

DATASET_DIR = PROJECT_ROOT / "real_data" / "dataset"
RESULT_DIR = DATASET_DIR / "blind_annotation_result"

GOLD_VERSION = "mentor-blind-gold-v2-20260811"

# 可映射到核心假设的披露类型，与 sample_blind_annotation.QUOTA_RELEVANT 同一口径。
RELEVANT_CATEGORIES = frozenset(
    {
        "产销数据",
        "定期报告",
        "业绩预告",
        "药品研发进展",
        "药品注册与上市",
        "融资",
        "投资与产能",
        "订单与合同",
        "风险与异动",
        "集采与准入",
    }
)

DIRECTIONS = ("支持", "冲突", "中性", "无关")


def read_csv(path) -> list[dict[str, str]]:
    """读 CSV。

    容忍双 BOM：回收文件经 Excel 二次保存后会带两个 BOM，
    `utf-8-sig` 只吃掉一个，剩下的会粘在首个字段名上导致 KeyError。
    """
    text = path.read_bytes().decode("utf-8-sig", errors="replace").lstrip("\ufeff")
    return list(csv.DictReader(text.splitlines()))


def cohen_kappa(left: list[str], right: list[str]) -> tuple[float, float, float]:
    """返回 (观测一致率, 期望一致率, kappa)。"""
    total = len(left)
    observed = sum(1 for a, b in zip(left, right, strict=True) if a == b) / total
    ca, cb = Counter(left), Counter(right)
    expected = sum(ca[k] / total * cb[k] / total for k in set(ca) | set(cb))
    kappa = (observed - expected) / (1 - expected) if expected < 1 else float("nan")
    return observed, expected, kappa


def validate(gold: list[dict], template: list[dict]) -> list[str]:
    """校验回收结果可用。题面被改动过就不能与原抽样对齐，必须报错而不是静默继续。"""
    problems: list[str] = []
    if len(gold) != len(template):
        problems.append(f"回收 {len(gold)} 行，原表 {len(template)} 行")
        return problems

    info_columns = (
        "序号",
        "公司",
        "披露日期",
        "公告标题",
        "原文链接",
        "H1-需求与出货",
        "H2-盈利质量",
        "H3-产能与扩张",
    )
    for row, ref in zip(gold, template, strict=True):
        for column in info_columns:
            if row[column].strip() != ref[column].strip():
                problems.append(f"#{row['序号']} 题面列 {column} 被改动")
        if row["影响方向"] not in DIRECTIONS:
            problems.append(f"#{row['序号']} 方向取值非法: {row['影响方向']!r}")
        # 无关 = 不进证据链，此时填假设是自相矛盾的
        if row["影响方向"] == "无关" and row["关联假设"]:
            problems.append(f"#{row['序号']} 判无关但填了关联假设")
        if row["影响方向"] != "无关" and not row["关联假设"]:
            problems.append(f"#{row['序号']} 有方向但关联假设为空")
        for column in ("判断理由", "标注人", "标注时间"):
            if not row[column].strip():
                problems.append(f"#{row['序号']} {column} 为空")
        try:
            datetime.fromisoformat(row["标注时间"])
        except ValueError:
            problems.append(f"#{row['序号']} 标注时间非 ISO 8601: {row['标注时间']!r}")
    return problems


def analyse(gold: list[dict], events: dict[tuple[str, str, str], dict]) -> dict:
    paired = [(row, events[(row["公司"], row["披露日期"], row["公告标题"])]) for row in gold]
    total = len(paired)

    gold_direction = [row["影响方向"] for row, _ in paired]
    pipe_direction = [event["annotator_a_direction"] for _, event in paired]
    observed, expected, kappa = cohen_kappa(gold_direction, pipe_direction)

    # 筛选能力：正类 = 金标认为该条进证据链（有关联假设）
    gold_relevant = [row["关联假设"] != "" for row, _ in paired]
    pipe_relevant = [event["annotator_a_hypothesis"] != "" for _, event in paired]
    tp = sum(1 for g, p in zip(gold_relevant, pipe_relevant, strict=True) if g and p)
    fp = sum(1 for g, p in zip(gold_relevant, pipe_relevant, strict=True) if not g and p)
    fn = sum(1 for g, p in zip(gold_relevant, pipe_relevant, strict=True) if g and not p)
    tn = sum(1 for g, p in zip(gold_relevant, pipe_relevant, strict=True) if not g and not p)

    # 方向能力单独在「双方都认为相关」的子集上算：混进筛选分歧会把两件事搅在一起
    both = [
        (row, event) for row, event in paired if row["关联假设"] and event["annotator_a_hypothesis"]
    ]
    direction_hit = sum(
        1 for row, event in both if row["影响方向"] == event["annotator_a_direction"]
    )

    by_category: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for row, event in paired:
        stat = by_category[event["category"]]
        stat[1] += 1
        if row["影响方向"] == event["annotator_a_direction"]:
            stat[0] += 1

    by_split: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for row, event in paired:
        stat = by_split[event["split"]]
        stat[1] += 1
        if row["影响方向"] == event["annotator_a_direction"]:
            stat[0] += 1

    # 管道判中性、金标判出方向的条目——这是本轮最大的单一偏差来源
    neutral_to_direction = [
        {
            "序号": row["序号"],
            "公司": row["公司"],
            "类型": event["category"],
            "金标方向": row["影响方向"],
            "标题": row["公告标题"],
        }
        for row, event in paired
        if event["annotator_a_direction"] == "中性" and row["影响方向"] != "中性"
    ]

    disagreements = [
        {
            "序号": row["序号"],
            "公司": row["公司"],
            "披露日期": row["披露日期"],
            "类型": event["category"],
            "裁决规则": event["ruling_rule"] or "",
            "金标方向": row["影响方向"],
            "金标假设": row["关联假设"],
            "管道方向": event["annotator_a_direction"],
            "标题": row["公告标题"],
            "金标理由": row["判断理由"],
        }
        for row, event in paired
        if row["影响方向"] != event["annotator_a_direction"]
    ]

    return {
        "gold_version": GOLD_VERSION,
        "generated_at": datetime.now(UTC).astimezone().isoformat(),
        "n": total,
        "annotators": sorted({row["标注人"] for row in gold}),
        "direction": {
            "observed_agreement": round(observed, 4),
            "expected_agreement": round(expected, 4),
            "cohen_kappa": round(kappa, 4),
            "gold_distribution": dict(Counter(gold_direction)),
            "pipeline_distribution": dict(Counter(pipe_direction)),
        },
        "screening": {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
            "precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "recall": round(tp / (tp + fn), 4) if tp + fn else None,
            "accuracy": round((tp + tn) / total, 4),
            "miss_rate": round(fn / (tp + fn), 4) if tp + fn else None,
            "irrelevant_alert_rate": round(fp / (tp + fp), 4) if tp + fp else None,
        },
        "direction_on_shared_relevant": {
            "n": len(both),
            "hit": direction_hit,
            "rate": round(direction_hit / len(both), 4) if both else None,
        },
        "hypothesis_agreement": round(
            sum(1 for row, event in paired if row["关联假设"] == event["annotator_a_hypothesis"])
            / total,
            4,
        ),
        "by_category": {
            cat: {"hit": hit, "n": num, "rate": round(hit / num, 4)}
            for cat, (hit, num) in sorted(by_category.items(), key=lambda kv: kv[1][0] / kv[1][1])
        },
        "by_split": {
            sp: {"hit": hit, "n": num, "rate": round(hit / num, 4)}
            for sp, (hit, num) in by_split.items()
        },
        "neutral_to_direction": neutral_to_direction,
        "disagreements": disagreements,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="用独立盲标金标评测标注管道")
    parser.add_argument(
        "--gold", default=str(RESULT_DIR / "mentor_blind_annotation_v2_annotated.csv")
    )
    parser.add_argument("--out", default=str(RESULT_DIR / "blind_gold_analysis.json"))
    args = parser.parse_args()

    from pathlib import Path

    gold = read_csv(Path(args.gold))
    template = read_csv(DATASET_DIR / "mentor_blind_annotation_v2.csv")

    problems = validate(gold, template)
    if problems:
        for item in problems:
            print(f"  [问题] {item}")
        raise SystemExit("回收结果未通过校验，不产出指标")

    events = {
        (e["company"], e["disclosure_time"][:10], e["title"]): e
        for e in read_csv(DATASET_DIR / "events.csv")
    }
    report = analyse(gold, events)
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    screening = report["screening"]
    direction = report["direction"]
    shared = report["direction_on_shared_relevant"]
    print(f"{GOLD_VERSION}: n={report['n']}，标注人={report['annotators']}")
    print(
        f"  筛选  精确率={screening['precision']:.1%} 召回率={screening['recall']:.1%} "
        f"无关提醒率={screening['irrelevant_alert_rate']:.1%} 漏报率={screening['miss_rate']:.1%}"
    )
    print(
        f"  方向  全样本一致率={direction['observed_agreement']:.1%} "
        f"kappa={direction['cohen_kappa']:.3f}；"
        f"共同相关子集 {shared['hit']}/{shared['n']}={shared['rate']:.1%}"
    )
    print(f"  管道判中性而金标有方向: {len(report['neutral_to_direction'])} 条")
    print(f"  写入 {args.out}")


if __name__ == "__main__":
    main()
