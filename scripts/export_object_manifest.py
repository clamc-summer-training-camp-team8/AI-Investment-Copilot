"""Export every source-object version for backup/recovery verification."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import settings
from app.services.object_store import S3ObjectStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--archive-dir", type=Path)
    args = parser.parse_args()

    store = S3ObjectStore(settings)
    store.ensure_bucket()
    manifest = (
        store.export_version_archive(args.archive_dir.resolve())
        if args.archive_dir
        else store.version_manifest()
    )
    manifest["generated_at"] = datetime.now(UTC).isoformat()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
