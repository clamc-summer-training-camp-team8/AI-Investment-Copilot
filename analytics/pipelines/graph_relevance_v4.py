"""Freeze and consume the ``graph-relevance-v4-blind`` evaluation package.

The workflow separates three moments that must not be conflated:

1. researchers freeze new queries/candidates without relevance labels;
2. tuning is closed by hashing the release-candidate implementation;
3. labels are imported and evaluated exactly once.

It cannot replace organizational access control, but it makes accidental label exposure,
post-label code changes and repeated blind evaluation machine-detectable.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from analytics.evaluation.graph_rag_benchmark import run_benchmark, update_quality_report
from app.core.config import PROJECT_ROOT

GOLD_VERSION = "graph-relevance-v4-blind"
SCHEMA_VERSION = "graph-relevance-blind-package-v1"
MINIMUM_QUERIES = 30
MINIMUM_CANDIDATES_PER_QUERY = 8
SEED = 20260826

BASE_COLUMNS = (
    "关系样本ID",
    "事件样本ID",
    "查询ID",
    "公司",
    "证券代码",
    "检索截止时间",
    "查询假设",
    "候选文档ID",
    "候选公告标题",
    "候选发布日期",
    "候选原文链接",
    "关键证据定位",
    "关键证据原文",
)
LABEL_COLUMNS = ("相关性等级", "关系路径可成立", "标注理由", "标注员", "标注时间")
VALID_GRADES = frozenset({"0-无关", "1-弱相关", "2-间接相关", "3-直接相关"})
VALID_PATHS = frozenset({"是", "否"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _write_csv(path: Path, rows: list[dict[str, str]], columns: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=columns,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _validate_annotation_time(value: str, relation_id: str) -> str:
    annotation_time = value.strip()
    if not annotation_time:
        raise ValueError(f"专业标注缺少标注时间：{relation_id}")
    try:
        parsed = datetime.fromisoformat(annotation_time)
    except ValueError as error:
        raise ValueError(f"标注时间无效：{relation_id}") from error
    if parsed.tzinfo is None:
        raise ValueError(f"标注时间缺少时区：{relation_id}")
    return annotation_time


def _validate_label_fields(row: dict[str, str], relation_id: str) -> None:
    if row.get("相关性等级", "").strip() not in VALID_GRADES:
        raise ValueError(f"相关性等级无效：{relation_id}")
    if row.get("关系路径可成立", "").strip() not in VALID_PATHS:
        raise ValueError(f"关系路径判断无效：{relation_id}")
    if not row.get("标注理由", "").strip() or not row.get("标注员", "").strip():
        raise ValueError(f"专业标注缺少理由或标注员：{relation_id}")
    _validate_annotation_time(row.get("标注时间", ""), relation_id)


def merge_extracted_labels(
    package_dir: Path,
    labels_json_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Merge workbook-extracted labels onto the immutable frozen candidate pool.

    Workbook copies of the query/candidate columns are deliberately ignored. This
    prevents Excel formatting or accidental researcher edits from changing the
    frozen evaluation questions during import.
    """

    blind_manifest = json.loads((package_dir / "blind_manifest.json").read_text(encoding="utf-8"))
    annotation_path = package_dir / "researcher" / "annotation.csv"
    if _sha256(annotation_path) != blind_manifest["files"]["researcher/annotation.csv"]:
        raise ValueError("研究员空白标注表哈希不匹配")
    frozen_rows = _read_csv(annotation_path)
    frozen_ids = [row["关系样本ID"].strip() for row in frozen_rows]

    payload = json.loads(labels_json_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError("工作簿标签提取文件必须是对象数组")
    extracted_rows: list[dict[str, str]] = [
        {str(key): str(value) if value is not None else "" for key, value in item.items()}
        for item in payload
    ]
    extracted_ids = [row.get("关系样本ID", "").strip() for row in extracted_rows]
    if any(not relation_id for relation_id in extracted_ids):
        raise ValueError("工作簿标签包含空关系样本ID")
    if len(set(extracted_ids)) != len(extracted_ids):
        raise ValueError("工作簿标签包含重复关系样本ID")
    if set(extracted_ids) != set(frozen_ids) or len(extracted_ids) != len(frozen_ids):
        raise ValueError("工作簿标签与冻结关系样本集合不一致")

    labels_by_id: dict[str, dict[str, str]] = {}
    for row, relation_id in zip(extracted_rows, extracted_ids, strict=True):
        labels = {column: row.get(column, "").strip() for column in LABEL_COLUMNS}
        _validate_label_fields(labels, relation_id)
        labels_by_id[relation_id] = labels

    merged = [
        {column: row.get(column, "") for column in BASE_COLUMNS}
        | labels_by_id[row["关系样本ID"].strip()]
        for row in frozen_rows
    ]
    _write_csv(output_path, merged, (*BASE_COLUMNS, *LABEL_COLUMNS))
    return {
        "gold_version": blind_manifest["gold_version"],
        "rows": len(merged),
        "queries": len({row["查询ID"] for row in merged}),
        "annotators": sorted({row["标注员"] for row in merged}),
        "output": str(output_path),
        "sha256": _sha256(output_path),
    }


def _validate_base(
    rows: list[dict[str, str]],
    *,
    include_v4_exclusions: bool = False,
    include_v5_exclusions: bool = False,
) -> dict[str, int]:
    if not rows:
        raise ValueError("v4 候选池不能为空")
    missing = set(BASE_COLUMNS) - set(rows[0])
    if missing:
        raise ValueError(f"v4 候选池缺少字段：{sorted(missing)}")
    leaked = [
        column for column in LABEL_COLUMNS if any(row.get(column, "").strip() for row in rows)
    ]
    if leaked:
        raise ValueError(f"冻结前候选池不得包含标签：{leaked}")
    relation_ids = [row["关系样本ID"].strip() for row in rows]
    if any(not value for value in relation_ids) or len(set(relation_ids)) != len(relation_ids):
        raise ValueError("关系样本ID必须非空且唯一")
    counts = Counter(row["查询ID"].strip() for row in rows)
    if "" in counts:
        raise ValueError("查询ID不能为空")
    if len(counts) < MINIMUM_QUERIES:
        raise ValueError(f"v4 至少需要 {MINIMUM_QUERIES} 个新查询，当前 {len(counts)}")
    too_small = {
        query_id: count
        for query_id, count in counts.items()
        if count < MINIMUM_CANDIDATES_PER_QUERY
    }
    if too_small:
        raise ValueError(f"每个查询至少需要 {MINIMUM_CANDIDATES_PER_QUERY} 个候选：{too_small}")

    v3_path = (
        PROJECT_ROOT
        / "analytics"
        / "datasets"
        / "final-gold-v3-20260826"
        / "final_graph_relevance_gold_v3.csv"
    )
    v3_rows = _read_csv(v3_path) if v3_path.is_file() else []
    v3_query_ids = {row.get("查询ID", "").strip() for row in v3_rows}
    reused_queries = sorted(set(counts) & v3_query_ids)
    if reused_queries:
        raise ValueError(f"v4 不得复用 v3 查询ID：{reused_queries}")
    v3_urls = {row.get("候选原文链接", "").strip() for row in v3_rows}
    reused_urls = sorted({row.get("候选原文链接", "").strip() for row in rows} & v3_urls - {""})
    if reused_urls:
        raise ValueError(f"v4 不得复用 v3 候选原文：{reused_urls[:5]}")
    if include_v4_exclusions:
        v4_path = (
            PROJECT_ROOT
            / "outputs"
            / "graph-relevance-v4-final"
            / "final_graph_relevance_gold_v4.csv"
        )
        v4_rows = _read_csv(v4_path) if v4_path.is_file() else []
        v4_query_ids = {row.get("查询ID", "").strip() for row in v4_rows}
        reused_v4_queries = sorted(set(counts) & v4_query_ids)
        if reused_v4_queries:
            raise ValueError(f"新盲测不得复用 v4 查询ID：{reused_v4_queries}")
        v4_urls = {row.get("候选原文链接", "").strip() for row in v4_rows}
        reused_v4_urls = sorted(
            {row.get("候选原文链接", "").strip() for row in rows} & v4_urls - {""}
        )
        if reused_v4_urls:
            raise ValueError(f"新盲测不得复用 v4 候选原文：{reused_v4_urls[:5]}")
    if include_v5_exclusions:
        v5_path = (
            PROJECT_ROOT
            / "outputs"
            / "graph-relevance-v5-final"
            / "final_graph_relevance_gold_v5.csv"
        )
        v5_rows = _read_csv(v5_path) if v5_path.is_file() else []
        v5_query_ids = {row.get("查询ID", "").strip() for row in v5_rows}
        reused_v5_queries = sorted(set(counts) & v5_query_ids)
        if reused_v5_queries:
            raise ValueError(f"新盲测不得复用 v5 查询ID：{reused_v5_queries}")
        v5_urls = {row.get("候选原文链接", "").strip() for row in v5_rows}
        reused_v5_urls = sorted(
            {row.get("候选原文链接", "").strip() for row in rows} & v5_urls - {""}
        )
        if reused_v5_urls:
            raise ValueError(f"新盲测不得复用 v5 候选原文：{reused_v5_urls[:5]}")

    query_dimensions: dict[str, tuple[str, str, str, str]] = {}
    query_documents: dict[str, set[str]] = {}
    for row in rows:
        cutoff = datetime.fromisoformat(row["检索截止时间"])
        if cutoff.tzinfo is None:
            raise ValueError(f"检索截止时间缺少时区：{row['关系样本ID']}")
        published = datetime.fromisoformat(row["候选发布日期"])
        if published.tzinfo is None:
            raise ValueError(f"候选发布日期缺少时区：{row['关系样本ID']}")
        if published > cutoff:
            raise ValueError(f"候选晚于检索截止时间：{row['关系样本ID']}")
        source_url = row["候选原文链接"].strip()
        if urlparse(source_url).scheme not in {"http", "https"}:
            raise ValueError(f"候选原文链接无效：{row['关系样本ID']}")
        if not row["候选文档ID"].strip() or not row["候选公告标题"].strip():
            raise ValueError(f"候选文档ID或公告标题为空：{row['关系样本ID']}")
        if not row["关键证据定位"].strip():
            raise ValueError(f"关键证据定位为空：{row['关系样本ID']}")
        if not row["关键证据原文"].strip():
            raise ValueError(f"关键证据原文为空：{row['关系样本ID']}")

        query_id = row["查询ID"].strip()
        dimensions = (
            row["公司"].strip(),
            row["证券代码"].strip(),
            row["检索截止时间"].strip(),
            row["查询假设"].strip(),
        )
        if not all(dimensions):
            raise ValueError(f"查询题面字段为空：{row['关系样本ID']}")
        previous = query_dimensions.setdefault(query_id, dimensions)
        if previous != dimensions:
            raise ValueError(f"同一查询的题面字段不一致：{query_id}")
        document_ids = query_documents.setdefault(query_id, set())
        document_id = row["候选文档ID"].strip()
        if document_id in document_ids:
            raise ValueError(f"同一查询存在重复候选文档：{query_id}/{document_id}")
        document_ids.add(document_id)
    return dict(counts)


def _gold_suffix(gold_version: str) -> str:
    matched = re.fullmatch(r"graph-relevance-(v\d+)-blind", gold_version)
    if not matched:
        raise ValueError(f"盲测版本格式无效：{gold_version}")
    return matched.group(1)


def freeze_candidate_pool(
    source: Path,
    output_dir: Path,
    *,
    gold_version: str = GOLD_VERSION,
) -> dict[str, Any]:
    rows = _read_csv(source)
    _gold_suffix(gold_version)
    gold_suffix = _gold_suffix(gold_version)
    counts = _validate_base(
        rows,
        include_v4_exclusions=gold_version != GOLD_VERSION,
        include_v5_exclusions=int(gold_suffix.removeprefix("v")) >= 6,
    )
    rng = random.Random(SEED)
    # 只打乱同一查询内的候选顺序，避免原始数据顺序形成隐式相关性提示。
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["查询ID"], []).append(row)
    frozen_rows: list[dict[str, str]] = []
    for query_id in sorted(grouped):
        candidates = list(grouped[query_id])
        rng.shuffle(candidates)
        frozen_rows.extend(candidates)

    tuner_path = output_dir / "tuner" / "candidate_pool.csv"
    researcher_path = output_dir / "researcher" / "annotation.csv"
    _write_csv(tuner_path, frozen_rows, BASE_COLUMNS)
    annotation_rows = [row | {column: "" for column in LABEL_COLUMNS} for row in frozen_rows]
    _write_csv(researcher_path, annotation_rows, (*BASE_COLUMNS, *LABEL_COLUMNS))
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "gold_version": gold_version,
        "state": "candidate_pool_frozen",
        "frozen_at": datetime.now(UTC).isoformat(),
        "random_seed": SEED,
        "queries": len(counts),
        "rows": len(rows),
        "minimum_candidates_per_query": min(counts.values()),
        "requirements": {
            "minimum_queries": MINIMUM_QUERIES,
            "minimum_candidates_per_query": MINIMUM_CANDIDATES_PER_QUERY,
        },
        "blindness": {
            "tuner_package_contains_labels": False,
            "forbidden_tuner_columns": list(LABEL_COLUMNS),
            "researcher_package_separate": True,
        },
        "files": {
            "tuner/candidate_pool.csv": _sha256(tuner_path),
            "researcher/annotation.csv": _sha256(researcher_path),
        },
    }
    _write_json(output_dir / "blind_manifest.json", manifest)
    return manifest


def _git_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or "unavailable"


def lock_release_candidate(package_dir: Path) -> dict[str, Any]:
    manifest_path = package_dir / "blind_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tracked = (
        PROJECT_ROOT / "app" / "ai" / "retrieval.py",
        PROJECT_ROOT / "app" / "ai" / "graph_rag.py",
        PROJECT_ROOT / "app" / "services" / "graph_rag.py",
        PROJECT_ROOT / "analytics" / "evaluation" / "graph_rag_benchmark.py",
    )
    payload = {
        "schema_version": "graph-rag-model-lock-v1",
        "gold_version": manifest["gold_version"],
        "locked_at": datetime.now(UTC).isoformat(),
        "git_revision": _git_revision(),
        "candidate_pool_sha256": manifest["files"]["tuner/candidate_pool.csv"],
        "implementation_sha256": {
            path.relative_to(PROJECT_ROOT).as_posix(): _sha256(path) for path in tracked
        },
        "weights": {
            "fusion_text": 0.25,
            "fusion_bm25": 0.5,
            "fusion_graph": 1.0,
            "fusion_report_prior": 1.0,
            "fusion_rrf_k": 1,
            "graph_internal_text": 0.35,
            "graph_internal_relation": 0.65,
        },
        "threshold_policy": {
            "version": "graph-rag-v6-gates-v1",
            "absolute_quality_thresholds_frozen": True,
            "candidate_pool_compliance_rate": 1.0,
            "maximum_recall_regression_vs_text": 0.01,
            "rationale": (
                "允许最多 1 个百分点 Recall@5 相对波动，但仍要求绝对 Recall@5>=0.80，"
                "并保留 NDCG@5、MRR、Top1、路径引用、候选池与零泄漏硬门。"
            ),
        },
        "thresholds_changed_after_v5": True,
    }
    _write_json(package_dir / "model_lock.json", payload)
    return payload


def _validate_model_lock(package_dir: Path, candidate_pool_sha256: str) -> dict[str, Any]:
    model_lock_path = package_dir / "model_lock.json"
    if not model_lock_path.is_file():
        raise ValueError("必须先冻结调参版本 model_lock.json，再导入标签")
    model_lock = json.loads(model_lock_path.read_text(encoding="utf-8"))
    blind_manifest = json.loads((package_dir / "blind_manifest.json").read_text(encoding="utf-8"))
    if model_lock.get("gold_version") != blind_manifest.get("gold_version"):
        raise ValueError("模型锁与盲测版本不一致")
    if model_lock.get("candidate_pool_sha256") != candidate_pool_sha256:
        raise ValueError("模型锁与冻结候选池不一致")
    for relative_path, expected_sha256 in model_lock.get("implementation_sha256", {}).items():
        implementation_path = PROJECT_ROOT / relative_path
        if not implementation_path.is_file() or _sha256(implementation_path) != expected_sha256:
            raise ValueError(f"模型锁定后实现发生变化：{relative_path}")
    return model_lock


def finalize_gold(
    package_dir: Path,
    annotated_path: Path,
    evaluator_dir: Path,
    *,
    researcher_attestation: str,
) -> dict[str, Any]:
    if not researcher_attestation.strip():
        raise ValueError("必须记录专业研究员声明")
    model_lock_path = package_dir / "model_lock.json"
    blind_manifest = json.loads((package_dir / "blind_manifest.json").read_text(encoding="utf-8"))
    frozen_path = package_dir / "tuner" / "candidate_pool.csv"
    if _sha256(frozen_path) != blind_manifest["files"]["tuner/candidate_pool.csv"]:
        raise ValueError("冻结候选池哈希不匹配")
    model_lock = _validate_model_lock(
        package_dir, blind_manifest["files"]["tuner/candidate_pool.csv"]
    )
    gold_version = str(blind_manifest["gold_version"])
    gold_suffix = _gold_suffix(gold_version)
    frozen = {row["关系样本ID"]: row for row in _read_csv(frozen_path)}
    annotated = _read_csv(annotated_path)
    annotated_ids = [row.get("关系样本ID", "") for row in annotated]
    if len(set(annotated_ids)) != len(annotated_ids):
        raise ValueError("回收标注包含重复关系样本ID")
    if set(frozen) != set(annotated_ids) or len(frozen) != len(annotated):
        raise ValueError("回收标注与冻结关系样本集合不一致")
    for row in annotated:
        relation_id = row["关系样本ID"]
        if any(
            row.get(column, "") != frozen[relation_id].get(column, "") for column in BASE_COLUMNS
        ):
            raise ValueError(f"回收标注修改了冻结题面：{relation_id}")
        _validate_label_fields(row, relation_id)

    gold_path = evaluator_dir / f"final_graph_relevance_gold_{gold_suffix}.csv"
    _write_csv(gold_path, annotated, (*BASE_COLUMNS, *LABEL_COLUMNS))
    manifest = {
        "schema_version": "graph-relevance-blind-final-v2",
        "gold_version": gold_version,
        "state": "labels_sealed_for_one_time_evaluation",
        "sealed_at": datetime.now(UTC).isoformat(),
        "researcher_attestation": researcher_attestation.strip(),
        "queries": len({row["查询ID"] for row in annotated}),
        "rows": len(annotated),
        "gold_sha256": _sha256(gold_path),
        "gold_file": gold_path.name,
        "candidate_pool_sha256": blind_manifest["files"]["tuner/candidate_pool.csv"],
        "model_lock_sha256": _sha256(model_lock_path),
        "model_locked_at": model_lock["locked_at"],
        "one_time_evaluation_consumed": False,
    }
    _write_json(evaluator_dir / "final_manifest.json", manifest)
    return manifest


def evaluate_once(
    evaluator_dir: Path,
    output_path: Path,
    quality_report_path: Path,
) -> dict[str, Any]:
    manifest_path = evaluator_dir / "final_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    receipt_path = evaluator_dir / "blind_evaluation_receipt.json"
    if receipt_path.exists() or manifest.get("one_time_evaluation_consumed"):
        raise RuntimeError("一次性盲测已经消费，禁止重复运行")
    gold_path = evaluator_dir / str(
        manifest.get("gold_file")
        or f"final_graph_relevance_gold_{_gold_suffix(str(manifest['gold_version']))}.csv"
    )
    if _sha256(gold_path) != manifest["gold_sha256"]:
        raise ValueError("盲测金标哈希不匹配")
    # 先写消费预约再揭盲执行。即使进程中途失败，receipt 也会阻止把同一盲测
    # 当成可反复调试的验证集；失败只能进入人工审计，不能静默重跑。
    _write_json(
        receipt_path,
        {
            "schema_version": "graph-relevance-blind-evaluation-receipt-v2",
            "gold_version": manifest["gold_version"],
            "state": "started",
            "started_at": datetime.now(UTC).isoformat(),
            "gold_sha256": manifest["gold_sha256"],
        },
    )
    report = run_benchmark(gold_path, evaluation_role="one_time_blind")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    update_quality_report(quality_report_path, report, output_path)
    manifest["state"] = "one_time_evaluation_completed"
    manifest["one_time_evaluation_consumed"] = True
    manifest["consumed_at"] = datetime.now(UTC).isoformat()
    manifest["benchmark_sha256"] = _sha256(output_path)
    _write_json(manifest_path, manifest)
    receipt = {
        "schema_version": "graph-relevance-blind-evaluation-receipt-v2",
        "gold_version": manifest["gold_version"],
        "state": "completed",
        "consumed_at": manifest["consumed_at"],
        "gold_sha256": manifest["gold_sha256"],
        "benchmark_sha256": manifest["benchmark_sha256"],
        "rollout_ready": report["rollout_ready"],
        "passed_gates": sum(gate["passed"] for gate in report["gates"]),
        "total_gates": len(report["gates"]),
    }
    _write_json(receipt_path, receipt)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze = subparsers.add_parser("freeze")
    freeze.add_argument("--source", type=Path, required=True)
    freeze.add_argument("--output-dir", type=Path, required=True)
    freeze.add_argument("--gold-version", default=GOLD_VERSION)
    lock = subparsers.add_parser("lock-model")
    lock.add_argument("--package-dir", type=Path, required=True)
    merge = subparsers.add_parser("merge-labels")
    merge.add_argument("--package-dir", type=Path, required=True)
    merge.add_argument("--labels-json", type=Path, required=True)
    merge.add_argument("--output", type=Path, required=True)
    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--package-dir", type=Path, required=True)
    finalize.add_argument("--annotated", type=Path, required=True)
    finalize.add_argument("--evaluator-dir", type=Path, required=True)
    finalize.add_argument("--researcher-attestation", required=True)
    evaluate = subparsers.add_parser("evaluate-once")
    evaluate.add_argument("--evaluator-dir", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    evaluate.add_argument("--quality-report", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        result = freeze_candidate_pool(
            args.source,
            args.output_dir,
            gold_version=args.gold_version,
        )
    elif args.command == "lock-model":
        result = lock_release_candidate(args.package_dir)
    elif args.command == "merge-labels":
        result = merge_extracted_labels(args.package_dir, args.labels_json, args.output)
    elif args.command == "finalize":
        result = finalize_gold(
            args.package_dir,
            args.annotated,
            args.evaluator_dir,
            researcher_attestation=args.researcher_attestation,
        )
    else:
        report = evaluate_once(args.evaluator_dir, args.output, args.quality_report)
        result = {
            "rollout_ready": report["rollout_ready"],
            "passed_gates": sum(gate["passed"] for gate in report["gates"]),
            "total_gates": len(report["gates"]),
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
