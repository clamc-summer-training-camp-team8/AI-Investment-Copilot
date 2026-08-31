from __future__ import annotations

from pathlib import Path

import pytest

from scripts.resolve_database_target import DatabaseTarget, resolve_database_target

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_从在线连接解析备份目标且不返回凭证() -> None:
    target = resolve_database_target(
        "postgresql+psycopg://copilot:super-secret@postgres:5432/copilot_dev?sslmode=disable"
    )

    assert target == DatabaseTarget(username="copilot", database="copilot_dev")
    assert "secret" not in repr(target)


@pytest.mark.parametrize(
    "database_url",
    [
        "mysql+pymysql://copilot:secret@mysql:3306/copilot_dev",
        "postgresql+psycopg://copilot:secret@postgres:5432/",
        "postgresql+psycopg://copilot%0Aevil:secret@postgres:5432/copilot_dev",
        "postgresql+psycopg://copilot:secret@postgres:5432/copilot%0Aevil",
    ],
)
def test_拒绝非_postgresql_或不能安全传给备份命令的目标(database_url: str) -> None:
    with pytest.raises(ValueError):
        resolve_database_target(database_url)


def test_集成备份脚本使用在线目标而非硬编码数据库() -> None:
    script = (PROJECT_ROOT / "deploy" / "integration" / "backup.sh").read_text(encoding="utf-8")

    assert "python -m scripts.resolve_database_target" in script
    assert 'pg_dump -U "$database_user" -d "$database_name"' in script
    assert "pg_dump -U copilot -d copilot" not in script
    assert "database-target.txt" in script
