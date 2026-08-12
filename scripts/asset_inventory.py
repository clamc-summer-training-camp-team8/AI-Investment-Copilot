"""Inventory/backfill report for P0-3 research assets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.uow import uow_scope


def build_report() -> dict[str, int]:
    with uow_scope() as uow:
        report = uow.assets.inventory()
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    text = json.dumps(build_report(), ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
