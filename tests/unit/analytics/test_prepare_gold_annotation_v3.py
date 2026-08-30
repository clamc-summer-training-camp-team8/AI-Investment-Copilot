from __future__ import annotations

import csv
import json

from analytics.pipelines.prepare_gold_annotation_v3 import EVENT_QUOTAS, build, sample_events


def _events() -> list[dict[str, str]]:
    with open("real_data/dataset/events.csv", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def test_v3_sample_is_frozen_stratified_and_has_no_duplicate_company_day() -> None:
    rows = sample_events(_events())

    assert len(rows) == 120
    assert rows == sample_events(_events())
    assert len({(row["company"], row["disclosure_time"][:10]) for row in rows}) == 120
    assert {
        category: sum(row["category"] == category for row in rows) for category in EVENT_QUOTAS
    } == EVENT_QUOTAS


def test_v3_annotation_inputs_are_blind_and_complete(tmp_path) -> None:
    stats = build(tmp_path)

    assert stats["events"] == 120
    assert stats["body_fact_tasks"] == 60
    assert stats["graph_relation_tasks"] == 180
    forbidden = set(
        json.loads((tmp_path / "gold_contract_v3.json").read_text(encoding="utf-8"))["blindness"][
            "forbidden_columns"
        ]
    )
    for path in (tmp_path / "tasks").glob("annotator_*.csv"):
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            assert not forbidden.intersection(reader.fieldnames or [])
            assert list(reader)

    with (tmp_path / "tasks" / "annotator_A_events.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        assert len(list(csv.DictReader(stream))) == 120
    with (tmp_path / "tasks" / "annotator_A_body_facts.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        assert len(list(csv.DictReader(stream))) == 60
    with (tmp_path / "tasks" / "annotator_A_graph_relevance.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        assert len(list(csv.DictReader(stream))) == 180
