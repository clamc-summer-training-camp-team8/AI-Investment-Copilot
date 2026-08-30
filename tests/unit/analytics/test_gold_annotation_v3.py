from __future__ import annotations

from pathlib import Path

from analytics.pipelines.gold_annotation_v3 import (
    export_consensus_gold,
    read_xlsx_sheet,
    validate_workbook,
)

PACKAGE = Path("outputs/gold-annotation-v3-20260826")


def test_generated_a_workbook_has_expected_rows_and_preserves_security_codes() -> None:
    workbook = PACKAGE / "02_标注员A_独立盲标工作簿_v3.xlsx"
    rows = read_xlsx_sheet(workbook, "事件语义_120")

    assert len(rows) == 120
    codes = [row["证券代码"].removeprefix("\u200b").removeprefix("'") for row in rows]
    assert all(len(code) in {5, 6} for code in codes)
    assert any(code.startswith("0") for code in codes)


def test_generated_templates_pass_structure_validation() -> None:
    assert not validate_workbook(
        PACKAGE / "02_标注员A_独立盲标工作簿_v3.xlsx",
        annotator="A",
        package_dir=PACKAGE,
        allow_empty=True,
    )
    assert not validate_workbook(
        PACKAGE / "03_标注员B_独立盲标工作簿_v3.xlsx",
        annotator="B",
        package_dir=PACKAGE,
        allow_empty=True,
    )


def test_completed_workbooks_export_only_high_confidence_consensus(tmp_path: Path) -> None:
    report = export_consensus_gold(
        PACKAGE / "annotator_A_completed_A_20260826.xlsx",
        PACKAGE / "annotator_B_completed_B-CODEX-FIN-01_20260826.xlsx",
        package_dir=PACKAGE,
        output_dir=tmp_path,
    )

    assert report["summary"] == {
        "total_samples": 360,
        "consensus_samples": 199,
        "pending_adjudication": 161,
        "consensus_coverage": 0.5528,
        "evaluation_ready": True,
        "production_gold_ready": False,
        "graph_rag_rollout_ready": False,
    }
    assert {item["task"]: item["consensus"] for item in report["tasks"]} == {
        "event": 73,
        "body_fact": 31,
        "graph_relevance": 95,
    }
    assert (tmp_path / "review" / "adjudication_queue.csv").is_file()
