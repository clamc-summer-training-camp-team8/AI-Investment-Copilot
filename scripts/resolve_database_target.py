"""从在线应用配置解析备份数据库目标，但绝不输出凭证。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.engine import make_url

from app.core.config import settings

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,62}$")


@dataclass(frozen=True)
class DatabaseTarget:
    username: str
    database: str


def resolve_database_target(database_url: str) -> DatabaseTarget:
    """返回 pg_dump 所需的用户和数据库名，不传播密码、主机或查询参数。"""

    parsed = make_url(database_url)
    if parsed.get_backend_name() != "postgresql":
        raise ValueError("在线数据库必须使用 PostgreSQL")
    username = parsed.username or ""
    database = parsed.database or ""
    if not _SAFE_IDENTIFIER.fullmatch(username):
        raise ValueError("DATABASE_URL 中的数据库用户不合法")
    if not _SAFE_IDENTIFIER.fullmatch(database):
        raise ValueError("DATABASE_URL 中的数据库名不合法")
    return DatabaseTarget(username=username, database=database)


def main() -> None:
    target = resolve_database_target(settings.database_url)
    print(target.username)
    print(target.database)


if __name__ == "__main__":
    main()
