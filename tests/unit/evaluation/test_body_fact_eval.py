from __future__ import annotations

from pathlib import Path

from analytics.evaluation.body_fact_eval import evaluate


def test_evaluation_supports_positive_and_negative_rows(tmp_path: Path) -> None:
    gold = tmp_path / "gold.csv"
    gold.write_text(
        "document_id,locator,body_text,expected_fact_type,expected_direction\n"
        "DOC-1,DOC-1#paragraph-1,营业收入同比增长25%,revenue_yoy,增长\n"
        "DOC-2,DOC-2#paragraph-1,公司本月交付20011辆,,\n",
        encoding="utf-8",
    )

    metrics = evaluate(gold)

    assert metrics.evaluable == 2
    assert metrics.true_positive == 1
    assert metrics.false_positive == 0
    assert metrics.false_negative == 0
    assert metrics.direction_accuracy == 1.0
