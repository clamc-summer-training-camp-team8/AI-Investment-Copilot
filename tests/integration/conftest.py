"""集成测试夹具。

需要真实 PostgreSQL。SQLite 不能替代：模型用了 JSONB、timestamptz 和
CheckConstraint，SQLite 的行为与之不同，用 SQLite 测出来的"通过"没有意义
（tests/README.md「数据库测试」）。

本地未起库时整层跳过，不让缺少 Docker 变成阻塞开发的理由。CI 里设了 CI=true，
此时连不上库直接失败——否则数据库配置错误会伪装成"全部通过"。
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Base


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    eng = create_engine(settings.database_url, pool_pre_ping=True, future=True)
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        message = f"数据库不可用：{exc.__class__.__name__}: {exc}"
        if os.environ.get("CI"):
            pytest.fail(message + "（CI 中集成测试不允许跳过）")
        pytest.skip(message + "，本地跳过集成测试")

    # 按 metadata 建表而非跑迁移：迁移链本身的往返由 test_migrations 单独验证。
    Base.metadata.create_all(eng)
    # create_all 不会给已有表补新增列；本地库未先 migrate 时会让模型与表结构不一致，
    # 随后的 API 测试才以难懂的 UndefinedColumn 失败。
    with eng.connect() as conn:
        thesis_columns = conn.execute(
            text(
                "select column_name from information_schema.columns "
                "where table_schema='public' and table_name='thesis'"
            )
        ).scalars()
        assert {"draft_suggestions", "is_current", "superseded_by_thesis_id"}.issubset(
            set(thesis_columns)
        ), "数据库迁移落后于 ORM，请先执行 `.venv\\Scripts\\alembic.exe upgrade head`"
        segment_columns = conn.execute(
            text(
                "select column_name from information_schema.columns "
                "where table_schema='public' and table_name='document_segment'"
            )
        ).scalars()
        assert {"content_kind", "extraction_method", "cell_range"}.issubset(
            set(segment_columns)
        ), "数据库缺少 P0-2 迁移，请先执行 `.venv\\Scripts\\alembic.exe upgrade head`"
        assert {
            "source",
            "industry",
            "document_revision",
            "ingestion_run",
            "ingestion_artifact",
            "segment_search_index",
            "segment_embedding",
            "thesis_revision_draft",
            "quant_market_dataset",
            "quant_signal_set",
            "quant_backtest_run",
        }.issubset(
            set(eng.dialect.get_table_names(conn))
        ), "数据库缺少 P0-3 迁移，请先执行 `.venv\\Scripts\\alembic.exe upgrade head`"
        document_columns = conn.execute(
            text(
                "select column_name from information_schema.columns "
                "where table_schema='public' and table_name='document'"
            )
        ).scalars()
        revision_columns = conn.execute(
            text(
                "select column_name from information_schema.columns "
                "where table_schema='public' and table_name='document_revision'"
            )
        ).scalars()
        assert {"deleted_at", "content_status"}.issubset(set(document_columns))
        assert {
            "tombstoned_at",
            "content_status",
            "authorization_basis",
            "authorization_verified_at",
        }.issubset(set(revision_columns))
        assert conn.execute(
            text("select exists(select 1 from pg_extension where extname='vector')")
        ).scalar()
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """每个测试跑在独立事务里并回滚，测试之间不共享数据、不依赖执行顺序。"""
    connection = engine.connect()
    transaction = connection.begin()
    sess = Session(bind=connection, expire_on_commit=False)
    try:
        yield sess
    finally:
        sess.close()
        # 断言约束的测试里 flush 会失败，PostgreSQL 中止事务后 SQLAlchemy 已经
        # 把它与连接解绑。此时再 rollback 会报 SAWarning，所以先查状态。
        if transaction.is_active:
            transaction.rollback()
        connection.close()
