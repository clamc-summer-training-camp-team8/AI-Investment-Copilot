"""Prepare the frozen, double-blind human annotation package for gold v3.

The generated files deliberately contain no pipeline/model labels.  They are
annotation inputs, not gold, until two researchers have completed them and an
adjudicator has resolved the disagreements.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import PROJECT_ROOT

DATASET_DIR = PROJECT_ROOT / "real_data" / "dataset"
DEFAULT_OUTPUT = PROJECT_ROOT / "outputs" / "gold-annotation-v3-20260826"
VERSION = "independent-gold-v3-20260826"
SEED = 20260826

# Quotas are based on source disclosure type, never on predicted/previous labels.
# Relevant-looking and noisy disclosures are both retained so precision, recall,
# false reminders and direction can be evaluated on the same frozen population.
EVENT_QUOTAS: dict[str, int] = {
    "产销数据": 14,
    "定期报告": 14,
    "药品研发进展": 8,
    "药品注册与上市": 8,
    "融资": 7,
    "业绩预告": 5,
    "投资与产能": 7,
    "订单与合同": 5,
    "风险与异动": 3,
    "集采与准入": 1,
    "治理": 14,
    "其他": 12,
    "程式化披露": 10,
    "股权激励": 4,
    "回购与持股变动": 5,
    "担保与关联交易": 3,
}

EVENT_FIELDS = (
    "序号",
    "样本ID",
    "公司",
    "证券代码",
    "行业",
    "市场",
    "披露时间",
    "时间精度",
    "公告标题",
    "原文链接",
    "核心观点",
    "H1-需求与出货",
    "H2-盈利质量",
    "H3-产能与扩张",
    "事件摘要",
    "事件类别",
    "主要关联假设",
    "影响方向",
    "影响强度",
    "直接性",
    "关键证据原文",
    "判断理由",
    "置信度",
    "数据问题",
    "标注人ID",
    "标注时间",
)

BODY_FIELDS = (
    "序号",
    "正文样本ID",
    "事件样本ID",
    "公告ID",
    "公司",
    "证券代码",
    "行业",
    "披露时间",
    "公告标题",
    "原文链接",
    "正文定位",
    "正文片段",
    "是否存在可抽取事实",
    "事实类型",
    "变化方向",
    "数值下限",
    "数值上限",
    "单位",
    "事实发生期",
    "判断理由",
    "置信度",
    "数据问题",
    "标注人ID",
    "标注时间",
)

GRAPH_FIELDS = (
    "序号",
    "关系样本ID",
    "事件样本ID",
    "查询ID",
    "公司",
    "证券代码",
    "行业",
    "检索截止时间",
    "查询假设",
    "候选公告标题",
    "候选原文链接",
    "相关性等级",
    "关系路径可成立",
    "关键证据原文",
    "判断理由",
    "置信度",
    "数据问题",
    "标注人ID",
    "标注时间",
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _load_hypotheses() -> dict[str, dict[str, Any]]:
    raw = json.loads((DATASET_DIR / "theses.json").read_text(encoding="utf-8"))
    result: dict[str, dict[str, Any]] = {}
    for thesis in raw:
        company = thesis["company"]
        if company in result:
            continue
        hypotheses = {
            hypothesis["hypothesis_id"].rsplit("-H", 1)[-1].split("-", 1)[0]: hypothesis
            for hypothesis in thesis["hypotheses"]
        }
        result[company] = {
            "core_view": thesis["core_view"],
            "hypotheses": hypotheses,
        }
    return result


def _event_hash(row: dict[str, str]) -> str:
    stable = "\u001f".join(
        row[key]
        for key in (
            "event_id",
            "security_id",
            "company",
            "title",
            "disclosure_time",
            "url",
        )
    )
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def sample_events(rows: list[dict[str, str]], *, seed: int = SEED) -> list[dict[str, str]]:
    """Stratified deterministic sample with company/day de-duplication."""

    by_category: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_category[row["category"]].append(row)

    rng = random.Random(seed)
    selected: list[dict[str, str]] = []
    company_counts: Counter[str] = Counter()
    split_counts: Counter[str] = Counter()
    taken_company_days: set[tuple[str, str]] = set()

    for category, quota in EVENT_QUOTAS.items():
        pool = sorted(by_category[category], key=lambda item: item["event_id"])
        if len(pool) < quota:
            raise ValueError(f"{category} only has {len(pool)} rows; quota is {quota}")
        rng.shuffle(pool)
        for index in range(quota):
            wanted_split = "out_of_sample" if index % 2 == 0 else "in_sample"
            fresh = [
                row
                for row in pool
                if (row["company"], row["disclosure_time"][:10]) not in taken_company_days
            ]
            split_pool = [row for row in fresh if row["split"] == wanted_split]
            candidates = split_pool or fresh
            if not candidates:
                raise ValueError(f"{category} cannot satisfy company/day de-duplication")
            chosen = min(
                candidates,
                key=lambda row: (
                    company_counts[row["company"]],
                    split_counts[row["split"]],
                    pool.index(row),
                ),
            )
            selected.append(chosen)
            company_counts[chosen["company"]] += 1
            split_counts[chosen["split"]] += 1
            taken_company_days.add((chosen["company"], chosen["disclosure_time"][:10]))
            pool.remove(chosen)

    if len(selected) != 120:
        raise ValueError(f"sample size is {len(selected)}, expected 120")
    random.Random(seed + 1).shuffle(selected)
    return selected


def _event_static_row(
    row: dict[str, str], sample_id: str, order: int, hypotheses: dict[str, dict[str, Any]]
) -> dict[str, str | int]:
    thesis = hypotheses[row["company"]]
    hs = thesis["hypotheses"]
    precise = row["disclosure_time_precise"] == "True"
    return {
        "序号": order,
        "样本ID": sample_id,
        "公司": row["company"],
        "证券代码": row["security_id"],
        "行业": row["industry"],
        "市场": row["market"],
        "披露时间": row["disclosure_time"],
        "时间精度": "精确" if precise else "仅日期（按盘后处理）",
        "公告标题": row["title"],
        "原文链接": row["url"],
        "核心观点": thesis["core_view"],
        "H1-需求与出货": hs["1"]["content"],
        "H2-盈利质量": hs["2"]["content"],
        "H3-产能与扩张": hs["3"]["content"],
        **{field: "" for field in EVENT_FIELDS[14:]},
    }


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _balanced_subset(
    selected: list[dict[str, str]], *, size: int, seed: int
) -> list[dict[str, str]]:
    """Pick a deterministic industry-balanced subset, retaining sample order later."""

    per_industry = size // 3
    rng = random.Random(seed)
    chosen: list[dict[str, str]] = []
    for industry in sorted({row["industry"] for row in selected}):
        pool = [row for row in selected if row["industry"] == industry]
        rng.shuffle(pool)
        pool.sort(key=lambda row: (row["category"] in {"治理", "其他", "程式化披露"},))
        chosen.extend(pool[:per_industry])
    if len(chosen) < size:
        remaining = [row for row in selected if row not in chosen]
        rng.shuffle(remaining)
        chosen.extend(remaining[: size - len(chosen)])
    return chosen


def _manifest(output_dir: Path, stats: dict[str, Any]) -> None:
    files = []
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        files.append(
            {
                "path": path.relative_to(output_dir).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            }
        )
    payload = {
        "package_version": VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "sampling_seed": SEED,
        "stats": stats,
        "files": files,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def build(output_dir: Path) -> dict[str, Any]:
    events = _read_csv(DATASET_DIR / "events.csv")
    hypotheses = _load_hypotheses()
    selected = sample_events(events)

    sample_ids = {row["event_id"]: f"G3-E{index:03d}" for index, row in enumerate(selected, 1)}
    master_rows: list[dict[str, Any]] = []
    for index, row in enumerate(selected, 1):
        thesis = hypotheses[row["company"]]
        master_rows.append(
            {
                "package_version": VERSION,
                "sample_id": sample_ids[row["event_id"]],
                "event_id": row["event_id"],
                "source_record_sha256": _event_hash(row),
                "security_id": row["security_id"],
                "company": row["company"],
                "industry": row["industry"],
                "market": row["market"],
                "disclosure_time": row["disclosure_time"],
                "disclosure_time_precise": row["disclosure_time_precise"],
                "title": row["title"],
                "url": row["url"],
                "sampling_category": row["category"],
                "dataset_split": row["split"],
                "core_view": thesis["core_view"],
                "h1": thesis["hypotheses"]["1"]["content"],
                "h2": thesis["hypotheses"]["2"]["content"],
                "h3": thesis["hypotheses"]["3"]["content"],
                "frozen_order": index,
            }
        )
    _write_csv(
        output_dir / "internal" / "frozen_sample_master.csv",
        tuple(master_rows[0]),
        master_rows,
    )

    # A and B receive exactly the same samples in different orders.  Neither
    # workbook contains sampling strata or any existing/predicted labels.
    for annotator, order_seed in (("A", SEED + 10), ("B", SEED + 20)):
        ordered = selected.copy()
        random.Random(order_seed).shuffle(ordered)
        rows = [
            _event_static_row(row, sample_ids[row["event_id"]], index, hypotheses)
            for index, row in enumerate(ordered, 1)
        ]
        _write_csv(output_dir / "tasks" / f"annotator_{annotator}_events.csv", EVENT_FIELDS, rows)

    body_subset = _balanced_subset(selected, size=60, seed=SEED + 30)
    body_ids = {row["event_id"]: f"G3-B{index:03d}" for index, row in enumerate(body_subset, 1)}
    graph_subset = _balanced_subset(selected, size=60, seed=SEED + 40)

    for annotator, order_seed in (("A", SEED + 50), ("B", SEED + 60)):
        ordered_body = body_subset.copy()
        random.Random(order_seed).shuffle(ordered_body)
        body_rows: list[dict[str, Any]] = []
        for index, row in enumerate(ordered_body, 1):
            body_rows.append(
                {
                    "序号": index,
                    "正文样本ID": body_ids[row["event_id"]],
                    "事件样本ID": sample_ids[row["event_id"]],
                    "公告ID": row["event_id"],
                    "公司": row["company"],
                    "证券代码": row["security_id"],
                    "行业": row["industry"],
                    "披露时间": row["disclosure_time"],
                    "公告标题": row["title"],
                    "原文链接": row["url"],
                    **{field: "" for field in BODY_FIELDS[10:]},
                }
            )
        _write_csv(
            output_dir / "tasks" / f"annotator_{annotator}_body_facts.csv",
            BODY_FIELDS,
            body_rows,
        )

        graph_rows: list[dict[str, Any]] = []
        for row in graph_subset:
            thesis = hypotheses[row["company"]]
            for hypothesis_number in ("1", "2", "3"):
                hypothesis = thesis["hypotheses"][hypothesis_number]
                graph_rows.append(
                    {
                        "关系样本ID": (
                            f"G3-R-{sample_ids[row['event_id']].split('-')[-1]}-H{hypothesis_number}"
                        ),
                        "事件样本ID": sample_ids[row["event_id"]],
                        "查询ID": f"{row['security_id']}-H{hypothesis_number}",
                        "公司": row["company"],
                        "证券代码": row["security_id"],
                        "行业": row["industry"],
                        "检索截止时间": row["disclosure_time"],
                        "查询假设": hypothesis["content"],
                        "候选公告标题": row["title"],
                        "候选原文链接": row["url"],
                        **{field: "" for field in GRAPH_FIELDS[11:]},
                    }
                )
        random.Random(order_seed + 1).shuffle(graph_rows)
        for index, graph_row in enumerate(graph_rows, 1):
            graph_row["序号"] = index
        _write_csv(
            output_dir / "tasks" / f"annotator_{annotator}_graph_relevance.csv",
            GRAPH_FIELDS,
            graph_rows,
        )

    adjudication_fields = (
        "任务类型",
        "样本ID",
        "A结果",
        "A理由",
        "B结果",
        "B理由",
        "裁决结果",
        "裁决理由",
        "裁决人ID",
        "裁决时间",
    )
    _write_csv(output_dir / "tasks" / "adjudication_queue_template.csv", adjudication_fields, [])

    contract = {
        "package_version": VERSION,
        "blindness": {
            "forbidden_columns": [
                "sampling_category",
                "dataset_split",
                "annotator_a_hypothesis",
                "annotator_a_direction",
                "annotator_b_hypothesis",
                "annotator_b_direction",
                "candidate_direction",
                "proxy_gold_direction",
                "model_output",
                "retrieval_rank",
                "retrieval_score",
            ],
            "double_annotation": "A/B annotate all rows independently",
        },
        "enums": {
            "事件类别": [
                "产销/需求",
                "收入/利润",
                "研发/注册",
                "产能/资本开支",
                "订单/合同",
                "融资/现金流",
                "风险/合规",
                "治理/其他",
                "无法判断",
            ],
            "主要关联假设": ["H1-需求与出货", "H2-盈利质量", "H3-产能与扩张", "无关", "信息不足"],
            "影响方向": ["支持", "冲突", "中性", "无关", "信息不足"],
            "影响强度": ["高", "中", "低", "不适用"],
            "直接性": ["直接", "间接", "不适用"],
            "数据问题": [
                "无",
                "原文不可达",
                "正文不可提取",
                "疑似重复",
                "时间不明确",
                "证券归属存疑",
                "其他",
            ],
            "是否存在可抽取事实": ["是", "否", "信息不足"],
            "事实类型": [
                "营业收入同比",
                "销量或交付量同比",
                "毛利率",
                "产能利用率",
                "资本开支",
                "订单金额",
                "其他",
                "不适用",
            ],
            "变化方向": ["上升", "下降", "持平", "无法判断", "不适用"],
            "相关性等级": ["3-直接相关", "2-间接相关", "1-弱相关", "0-无关", "9-信息不足"],
            "关系路径可成立": ["是", "否", "信息不足"],
            "置信度": [1, 2, 3, 4, 5],
        },
        "required_fields": {
            "event": [
                "事件摘要",
                "事件类别",
                "主要关联假设",
                "影响方向",
                "影响强度",
                "直接性",
                "判断理由",
                "置信度",
                "数据问题",
                "标注人ID",
                "标注时间",
            ],
            "body_fact": [
                "正文定位",
                "正文片段",
                "是否存在可抽取事实",
                "事实类型",
                "变化方向",
                "判断理由",
                "置信度",
                "数据问题",
                "标注人ID",
                "标注时间",
            ],
            "graph_relevance": [
                "相关性等级",
                "关系路径可成立",
                "判断理由",
                "置信度",
                "数据问题",
                "标注人ID",
                "标注时间",
            ],
        },
    }
    (output_dir / "gold_contract_v3.json").write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    stats = {
        "events": len(selected),
        "body_fact_tasks": len(body_subset),
        "graph_relation_tasks": len(graph_subset) * 3,
        "industry": dict(Counter(row["industry"] for row in selected)),
        "company": dict(Counter(row["company"] for row in selected)),
        "category": dict(Counter(row["category"] for row in selected)),
        "split": dict(Counter(row["split"] for row in selected)),
        "date_min": min(row["disclosure_time"] for row in selected),
        "date_max": max(row["disclosure_time"] for row in selected),
    }
    (output_dir / "workload_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _manifest(output_dir, stats)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare independent gold annotation v3")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    stats = build(args.output)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
