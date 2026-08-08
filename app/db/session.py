"""数据库会话。

会话生命周期由调用方（app/api 的依赖注入或 app/workers 的任务边界）管理。
业务写入与审计写入必须在同一事务内：审计缺失时业务动作应当回滚，
否则 FR-A-003 的可追溯性无法保证。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    echo=False,
    future=True,
)

SessionFactory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """事务边界。异常时回滚，保证审计与业务写入原子性。"""
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
