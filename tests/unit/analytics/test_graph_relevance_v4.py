from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from analytics.pipelines import graph_relevance_v4 as pipeline


def _pool(path: Path, *, queries: int = 30, candidates: int = 8) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=pipeline.BASE_COLUMNS)
        writer.writeheader()
        for query_index in range(queries):
            for candidate_index in range(candidates):
                writer.writerow(
                    {
                        "关系样本ID": f"V4-R{query_index:02d}-{candidate_index:02d}",
                        "事件样本ID": f"V4-E{query_index:02d}-{candidate_index:02d}",
                        "查询ID": f"V4-Q{query_index:02d}",
                        "公司": f"公司{query_index % 10}",
                        "证券代码": f"{query_index % 10:06d}",
                        "检索截止时间": "2026-08-26T18:00:00+08:00",
                        "查询假设": f"查询 {query_index} 的经营假设",
                        "候选文档ID": f"DOC-V4-{query_index:02d}-{candidate_index:02d}",
                        "候选公告标题": f"候选公告 {candidate_index}",
                        "候选发布日期": "2026-08-20T09:00:00+08:00",
                        "候选原文链接": (
                            "https://example.com/v4/" f"{query_index:02d}/{candidate_index:02d}.pdf"
                        ),
                        "关键证据定位": "第1页",
                        "关键证据原文": f"候选 {candidate_index} 的公开原文",
                    }
                )


def _annotate(source: Path, destination: Path) -> None:
    with source.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    with destination.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=(*pipeline.BASE_COLUMNS, *pipeline.LABEL_COLUMNS)
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                row
                | {
                    "相关性等级": "3-直接相关",
                    "关系路径可成立": "是",
                    "标注理由": "专业研究员独立阅读原文后的判断",
                    "标注员": "researcher-1",
                    "标注时间": "2026-08-27T10:00:00+08:00",
                }
            )


def test_v4_freeze_requires_30_queries_and_8_candidates(tmp_path: Path) -> None:
    source = tmp_path / "small.csv"
    _pool(source, queries=29)
    with pytest.raises(ValueError, match="至少需要 30"):
        pipeline.freeze_candidate_pool(source, tmp_path / "package")

    _pool(source, queries=30, candidates=7)
    with pytest.raises(ValueError, match="至少需要 8"):
        pipeline.freeze_candidate_pool(source, tmp_path / "package")


def test_blind_workflow_can_freeze_v5_version(tmp_path: Path) -> None:
    source = tmp_path / "pool.csv"
    package = tmp_path / "package"
    _pool(source)

    manifest = pipeline.freeze_candidate_pool(
        source,
        package,
        gold_version="graph-relevance-v5-blind",
    )
    lock = pipeline.lock_release_candidate(package)

    assert manifest["gold_version"] == "graph-relevance-v5-blind"
    assert lock["gold_version"] == "graph-relevance-v5-blind"
    assert b"\r\n" not in (package / "tuner" / "candidate_pool.csv").read_bytes()
    assert b"\r\n" not in (package / "researcher" / "annotation.csv").read_bytes()


def test_v4_tuner_package_has_no_labels_and_model_is_locked_before_finalize(
    tmp_path: Path,
) -> None:
    source = tmp_path / "pool.csv"
    package = tmp_path / "package"
    evaluator = tmp_path / "evaluator"
    annotated = tmp_path / "annotated.csv"
    _pool(source)
    manifest = pipeline.freeze_candidate_pool(source, package)

    with (package / "tuner" / "candidate_pool.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        assert not set(pipeline.LABEL_COLUMNS) & set(next(csv.reader(stream)))
    assert manifest["queries"] == 30
    assert manifest["minimum_candidates_per_query"] == 8

    _annotate(package / "researcher" / "annotation.csv", annotated)
    with pytest.raises(ValueError, match="先冻结调参版本"):
        pipeline.finalize_gold(
            package,
            annotated,
            evaluator,
            researcher_attestation="专业研究员独立完成标注",
        )

    pipeline.lock_release_candidate(package)
    final = pipeline.finalize_gold(
        package,
        annotated,
        evaluator,
        researcher_attestation="专业研究员独立完成标注",
    )
    assert final["gold_version"] == pipeline.GOLD_VERSION
    assert final["queries"] == 30
    assert final["rows"] == 240


def test_v4_merge_uses_frozen_base_fields_and_validates_exact_relation_set(
    tmp_path: Path,
) -> None:
    source = tmp_path / "pool.csv"
    package = tmp_path / "package"
    output = tmp_path / "annotated.csv"
    labels_path = tmp_path / "labels.json"
    _pool(source)
    pipeline.freeze_candidate_pool(source, package)
    frozen = pipeline._read_csv(package / "researcher" / "annotation.csv")
    labels = [
        {
            "关系样本ID": row["关系样本ID"],
            "查询假设": "工作簿中的题面即使被修改也不得导入",
            "相关性等级": "2-间接相关",
            "关系路径可成立": "是",
            "标注理由": "专业研究员独立阅读原文后的判断",
            "标注员": "researcher-1",
            "标注时间": "2026-08-27T10:00:00+08:00",
        }
        for row in frozen
    ]
    labels_path.write_text(json.dumps(labels, ensure_ascii=False), encoding="utf-8")

    merged = pipeline.merge_extracted_labels(package, labels_path, output)

    rows = pipeline._read_csv(output)
    assert merged["rows"] == 240
    assert rows[0]["查询假设"] == frozen[0]["查询假设"]
    assert rows[0]["相关性等级"] == "2-间接相关"

    labels.append(labels[0])
    labels_path.write_text(json.dumps(labels, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="重复关系样本ID"):
        pipeline.merge_extracted_labels(package, labels_path, output)


def test_v4_finalize_rejects_annotation_time_without_timezone(tmp_path: Path) -> None:
    source = tmp_path / "pool.csv"
    package = tmp_path / "package"
    evaluator = tmp_path / "evaluator"
    annotated = tmp_path / "annotated.csv"
    _pool(source)
    pipeline.freeze_candidate_pool(source, package)
    pipeline.lock_release_candidate(package)
    _annotate(package / "researcher" / "annotation.csv", annotated)
    rows = pipeline._read_csv(annotated)
    rows[0]["标注时间"] = "2026-08-27T10:00:00"
    pipeline._write_csv(annotated, rows, (*pipeline.BASE_COLUMNS, *pipeline.LABEL_COLUMNS))

    with pytest.raises(ValueError, match="缺少时区"):
        pipeline.finalize_gold(
            package,
            annotated,
            evaluator,
            researcher_attestation="专业研究员独立完成标注",
        )


def test_v4_blind_evaluation_can_only_be_consumed_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evaluator = tmp_path / "evaluator"
    evaluator.mkdir()
    gold = evaluator / "final_graph_relevance_gold_v4.csv"
    gold.write_text("gold", encoding="utf-8")
    digest = pipeline._sha256(gold)
    (evaluator / "final_manifest.json").write_text(
        json.dumps(
            {
                "gold_version": pipeline.GOLD_VERSION,
                "gold_sha256": digest,
                "one_time_evaluation_consumed": False,
            }
        ),
        encoding="utf-8",
    )
    report = {
        "rollout_ready": True,
        "gates": [{"passed": True}] * 12,
        "graph_rag": {
            "recall_at_k": {"5": 0.9},
            "mrr": 0.8,
            "top1_correctness": 0.75,
        },
        "safety": {
            "permission_leakage_count": 0,
            "security_leakage_count": 0,
            "future_leakage_count": 0,
        },
    }
    monkeypatch.setattr(pipeline, "run_benchmark", lambda _path, **_kwargs: report)
    monkeypatch.setattr(pipeline, "update_quality_report", lambda *_args: None)

    pipeline.evaluate_once(evaluator, tmp_path / "report.json", tmp_path / "quality.json")

    receipt = json.loads((evaluator / "blind_evaluation_receipt.json").read_text(encoding="utf-8"))
    assert receipt["passed_gates"] == 12
    manifest = json.loads((evaluator / "final_manifest.json").read_text(encoding="utf-8"))
    assert manifest["state"] == "one_time_evaluation_completed"
    with pytest.raises(RuntimeError, match="禁止重复运行"):
        pipeline.evaluate_once(evaluator, tmp_path / "report-2.json", tmp_path / "quality.json")
