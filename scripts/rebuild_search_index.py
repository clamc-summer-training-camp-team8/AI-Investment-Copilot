"""Rebuild the permission-bearing segment search projection from PostgreSQL facts."""

from app.services.uow import uow_scope


def main() -> None:
    with uow_scope() as uow:
        count = uow.assets.rebuild_search_index()
    print(f"检索索引已重建：{count} 个切片")


if __name__ == "__main__":
    main()
