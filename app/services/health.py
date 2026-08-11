"""Infrastructure readiness checks exposed through the service layer."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


def database_ready() -> tuple[bool, str]:
    # Local import keeps pure service-module tests from opening a database at import time.
    from app.db.session import engine

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        return False, type(exc).__name__
    return True, "ok"
