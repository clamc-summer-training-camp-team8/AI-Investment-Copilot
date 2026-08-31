"""受控校验或登记冻结行情候选；登记与默认版本切换严格分离。"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from app.db.repositories import build_uow
from app.db.session import session_scope
from app.services.quant import register_market_dataset, validate_market_dataset

_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


def _sha256(value: str) -> str:
    if not _SHA256_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "expected SHA-256 must be exactly 64 hexadecimal characters"
        )
    return value.lower()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="校验或登记受治理冻结行情；此命令不会改变在线默认行情配置。"
    )
    parser.add_argument("--manifest", type=Path, required=True, help="候选 manifest.json 路径")
    parser.add_argument("--expected-sha256", type=_sha256, required=True, help="审批后的清单哈希")
    parser.add_argument("--expected-dataset-id", required=True, help="审批后的数据集编号")
    parser.add_argument("--frozen-by", default="quant-controlled-publisher", help="审计操作者")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--dry-run", action="store_true", help="只校验文件和审批值，不写数据库")
    action.add_argument("--register", action="store_true", help="校验后幂等登记，不切换默认版本")
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.dry_run:
        record = validate_market_dataset(
            args.manifest,
            expected_sha256=args.expected_sha256,
            expected_dataset_id=args.expected_dataset_id,
            frozen_by=args.frozen_by,
        )
        action = "validated"
    else:
        with session_scope() as session:
            record = register_market_dataset(
                build_uow(session),
                manifest_path=args.manifest,
                expected_sha256=args.expected_sha256,
                expected_dataset_id=args.expected_dataset_id,
                frozen_by=args.frozen_by,
            )
        action = "registered"
    print(
        json.dumps(
            {
                "action": action,
                "dataset_id": record.dataset_id,
                "data_version": record.data_version,
                "manifest_path": record.manifest_path,
                "manifest_sha256": record.manifest_sha256,
                "default_changed": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
