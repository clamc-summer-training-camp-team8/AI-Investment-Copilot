"""Refresh the nine-company prior-ranked RAG knowledge base end to end."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SECURITY_IDS = (
    "000538",
    "600276",
    "603259",
    "00175",
    "002594",
    "09868",
    "002371",
    "603986",
    "688981",
)


def _run(*args: str) -> None:
    command = [sys.executable, "-m", *args]
    print("+", " ".join(command), flush=True)
    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply", action="store_true", help="显式确认刷新数据库索引、向量和先验快照"
    )
    parser.add_argument("--as-of", default="2026-08-24T23:59:59+08:00")
    parser.add_argument("--ranker-version", default="thesis-prior-nine-company-refresh-v1")
    parser.add_argument("--output-dir", type=Path, default=Path("analytics/experiments/latest"))
    args = parser.parse_args()
    if not args.apply:
        parser.error("刷新会写入数据库；请显式传入 --apply")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    _run("scripts.materialize_evidence_fact_segments", "--apply")
    _run("scripts.rebuild_search_index")
    _run("scripts.build_embeddings", "--version", "hash-char-2gram-v1")
    for security_id in SECURITY_IDS:
        _run(
            "scripts.build_ranking_priors",
            "--from-db",
            "--security-id",
            security_id,
            "--as-of",
            args.as_of,
            "--ranker-version",
            args.ranker_version,
        )
    _run(
        "scripts.report_knowledge_coverage",
        "--output",
        str(args.output_dir / "nine-company-coverage.md"),
    )
    _run(
        "scripts.evaluate_nine_company_retrieval",
        "--as-of",
        args.as_of,
        "--output",
        str(args.output_dir / "traceability-smoke.json"),
    )
    _run(
        "scripts.evaluate_nine_company_blind_gold",
        "--as-of",
        args.as_of,
        "--output",
        str(args.output_dir / "blind-retrieval-eval.json"),
    )


if __name__ == "__main__":
    main()
