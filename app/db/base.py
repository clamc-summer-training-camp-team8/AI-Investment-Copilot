"""ORM 基类与公共列类型。

所有时间列统一使用 timezone=True（PostgreSQL timestamptz）。字段字典
FLD-002/006/008 要求业务时区 Asia/Shanghai，naive datetime 由
app.core.timeutil 在入库前拦截。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from sqlalchemy import DateTime, MetaData, Numeric, String, func
from sqlalchemy.orm import DeclarativeBase, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


BizId = Annotated[str, mapped_column(String(64))]
ShortText = Annotated[str, mapped_column(String(255))]
Ratio = Annotated[Decimal, mapped_column(Numeric(18, 6))]

TimestampTz = Annotated[datetime, mapped_column(DateTime(timezone=True))]


def created_at_column():
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def updated_at_column():
    return mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
