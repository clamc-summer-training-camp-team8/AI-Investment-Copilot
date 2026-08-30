from __future__ import annotations

import argparse
import csv
from pathlib import Path


ROOT = Path(r"E:\product\AI-Investment-Copilot\outputs\Graph-RAG-v4-专业研究员盲标包-20260826")
CSV_PATH = ROOT / "v4_专业研究员独立盲标原始表.csv"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=30)
    parser.add_argument("--evidence", type=int, default=1000)
    args = parser.parse_args()

    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))

    for query_number in range(args.start, args.end + 1):
        query_id = f"V4-Q{query_number:03d}"
        group = [row for row in rows if row["查询ID"] == query_id]
        if not group:
            continue
        first = group[0]
        print(f"\n=== {query_id} | {first['公司']} | {first['查询假设']} ===")
        for index, row in enumerate(group, start=1):
            evidence = " ".join(row["关键证据原文"].split())
            if len(evidence) > args.evidence:
                evidence = evidence[: args.evidence] + "…"
            print(
                f"[{index}] {row['关系样本ID']} | {row['候选公告标题']} | "
                f"{row['候选发布日期']} | {row['关键证据定位']}\n{evidence}"
            )


if __name__ == "__main__":
    main()
