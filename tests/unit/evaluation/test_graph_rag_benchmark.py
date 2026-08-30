from __future__ import annotations

import json
from pathlib import Path

from analytics.evaluation.graph_rag_benchmark import (
    DEFAULT_GOLD,
    run_ablation_suite,
    run_benchmark,
    update_quality_report,
)


def test_final_gold_benchmark_uses_judged_pool_and_blocks_all_canaries() -> None:
    report = run_benchmark(DEFAULT_GOLD)

    assert report["dataset"] == {
        "rows": 180,
        "queries": 27,
        "positive_queries": 25,
        "securities": 9,
    }
    assert report["evaluation_protocol"]["gold_labels_used_for_graph_construction"] is False
    assert report["evaluation_protocol"]["candidate_pool_scope"] == "per_query_closed"
    assert report["graph_rag"]["unjudged_result_count"] == 0
    assert report["assist"]["rank_stability_rate"] < 1.0
    assert report["assist"]["candidate_pool_compliance_rate"] == 1.0
    assert report["safety"]["adversarial_canary_count"] == 81
    assert report["safety"]["permission_leakage_count"] == 0
    assert report["safety"]["security_leakage_count"] == 0
    assert report["safety"]["future_leakage_count"] == 0
    assert report["safety"]["canary_content_leakage_count"] == 0
    assert report["safety"]["path_provenance_rate"] == 1.0
    assert set(report["error_taxonomy"]["groups"]) == {
        "governance_hard_negative",
        "duplicate_disclosures",
        "too_many_positive_candidates",
        "graph_cannot_change_top1",
    }
    assert report["evaluation_role"] == "revealed_regression"
    assert report["evaluation_protocol"]["v3_may_authorize_rollout"] is False


def test_quality_report_is_updated_from_benchmark_without_claiming_false_pass(
    tmp_path: Path,
) -> None:
    benchmark = run_benchmark(DEFAULT_GOLD)
    quality = {
        "summary": {"graph_rag_rollout_ready": True},
        "gates": [
            {
                "code": "graph_rag_system_benchmark",
                "label": "Graph RAG 系统离线基准",
                "status": "passed",
                "message": "old",
            }
        ],
    }
    quality_path = tmp_path / "quality.json"
    quality_path.write_text(json.dumps(quality), encoding="utf-8")
    report_path = tmp_path / "benchmark.json"

    update_quality_report(quality_path, benchmark, report_path)

    updated = json.loads(quality_path.read_text(encoding="utf-8"))
    assert updated["summary"]["graph_rag_rollout_ready"] is False
    assert updated["gates"][0]["current"] is False
    assert updated["gates"][0]["status"] == "blocked"
    assert updated["system_benchmarks"]["graph_rag"]["authoritative_blind"] is False
    assert updated["system_benchmarks"]["graph_rag"]["graph_rag"]["mrr"] > 0


def test_each_p0_change_has_an_isolated_v3_ablation_and_explicit_fusion_candidate() -> None:
    suite = run_ablation_suite(DEFAULT_GOLD)

    assert [row["variant"]["name"] for row in suite["variants"]] == [
        "v1_baseline",
        "controlled_concepts_only",
        "announcement_prior_only",
        "bm25_only",
        "chinese_vector_only",
        "diversity_only",
        "p0_assisted_release_candidate",
        "p0_evidence_fusion_release_candidate",
    ]
    assert suite["weights_changed_between_variants"] is True
    assert suite["thresholds_changed_between_variants"] is False
    for row in suite["variants"][1:-2]:
        switches = [
            row["variant"]["enhanced_concepts"],
            row["variant"]["announcement_prior"],
            row["variant"]["bm25"],
            row["variant"]["chinese_vector"],
            row["variant"]["diversity"],
        ]
        assert sum(switches) == 1
    assert suite["variants"][-1]["variant"]["evidence_fusion"] is True


def test_v5_one_time_blind_can_mark_quality_center_graph_rag_ready(tmp_path: Path) -> None:
    quality_path = tmp_path / "quality.json"
    quality_path.write_text(
        json.dumps(
            {
                "summary": {"graph_rag_rollout_ready": False},
                "gates": [
                    {
                        "code": "graph_rag_system_benchmark",
                        "label": "Graph RAG 系统离线基准",
                        "status": "blocked",
                        "message": "pending",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    benchmark = {
        "gold_version": "graph-relevance-v5-blind",
        "evaluation_role": "one_time_blind",
        "benchmark_version": "test-v4",
        "generated_at": "2026-08-27T00:00:00+00:00",
        "rollout_ready": True,
        "text_baseline": {},
        "graph_rag": {
            "evaluated_queries": 30,
            "positive_queries": 30,
            "recall_at_k": {"5": 0.82},
            "mrr": 0.72,
            "top1_correctness": 0.73,
        },
        "safety": {
            "permission_leakage_count": 0,
            "security_leakage_count": 0,
            "future_leakage_count": 0,
        },
        "gates": [{"passed": True}] * 12,
    }

    update_quality_report(quality_path, benchmark, tmp_path / "v5-report.json")

    updated = json.loads(quality_path.read_text(encoding="utf-8"))
    assert updated["summary"]["graph_rag_rollout_ready"] is True
    assert updated["gates"][0]["status"] == "passed"
    assert updated["system_benchmarks"]["graph_rag"]["authoritative_blind"] is True
