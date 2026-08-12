"""Incrementally build one version of P1 retrieval embeddings."""

from __future__ import annotations

import argparse

from app.core.config import settings
from app.services import assets
from app.services.uow import uow_scope


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default=settings.embedding_version)
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()
    if not args.version:
        raise SystemExit("请通过 --version 或 EMBEDDING_VERSION 指定模型版本")
    total = 0
    while True:
        with uow_scope() as uow:
            created = assets.embed_pending_assets(
                uow, embedding_version=args.version, batch_size=args.batch_size
            )
        total += created
        print(f"embedding_version={args.version} batch={created} total={total}")
        if created == 0:
            break


if __name__ == "__main__":
    main()
