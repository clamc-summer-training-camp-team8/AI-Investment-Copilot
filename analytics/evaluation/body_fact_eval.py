"""正文事实抽取的独立评测入口。

金标 CSV 由第二名标注者独立填写，不允许从抽取规则自动生成。空模板只用于协作，
没有正文与期望事实的行会被明确计为不可评测，不会伪装成通过。
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.ingest.facts import extract_key_facts
from app.ingest.segmentation import Segment


@dataclass(frozen=True)
class Metrics:
    rows: int
    evaluable: int
    true_positive: int
    false_positive: int
    false_negative: int
    precision: float | None
    recall: float | None
    direction_accuracy: float | None


def evaluate(path: Path) -> Metrics:
    with path.open(encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    evaluable = [row for row in rows if row.get("body_text")]
    tp = fp = fn = direction_matches = 0
    for index, row in enumerate(evaluable, start=1):
        facts = extract_key_facts(
            [Segment(row["document_id"], row["locator"], index, row["body_text"])]
        )
        if not row.get("expected_fact_type"):
            fp += len(facts)
            continue
        matched = [fact for fact in facts if fact.fact_type == row["expected_fact_type"]]
        if not matched:
            fn += 1
            fp += len(facts)
            continue
        tp += 1
        fp += max(0, len(facts) - 1)
        direction_matches += int(matched[0].direction == row.get("expected_direction"))
    return Metrics(
        rows=len(rows),
        evaluable=len(evaluable),
        true_positive=tp,
        false_positive=fp,
        false_negative=fn,
        precision=tp / (tp + fp) if tp + fp else None,
        recall=tp / (tp + fn) if tp + fn else None,
        direction_accuracy=direction_matches / tp if tp else None,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gold", type=Path)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    metrics = evaluate(args.gold)
    rendered = json.dumps(asdict(metrics), ensure_ascii=False, indent=2)
    print(rendered)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if metrics.evaluable else 2


if __name__ == "__main__":
    raise SystemExit(main())
