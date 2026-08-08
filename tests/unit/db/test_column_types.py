"""时间列必须是 timestamptz。

这条曾经真的坏过：`base.py` 定义了 `TimestampTz` 但没有任何模型用它，模型里
写的是裸 `Mapped[datetime]`，SQLAlchemy 默认映射成 timestamp without time
zone。9 个列受影响，包括 published_at / disclosure_time / available_at /
generated_at——四类时间语义全中。

丢时区的后果不是报错而是静默错误：读回来的 datetime 是 naive，跨来源比较退回
naive 混算，DQ-003 的泄露判定和 DQ-006 的窗口标签判定随之失效。集成测试能抓
到，但集成测试需要数据库，本地常被跳过。所以在这里用纯元数据断言兜住，
`make test` 就能发现。
"""

from __future__ import annotations

from sqlalchemy import DateTime

from app.db.models import Base


def _datetime_columns() -> list[tuple[str, str, DateTime]]:
    return [
        (table.name, column.name, column.type)
        for table in Base.metadata.sorted_tables
        for column in table.columns
        if isinstance(column.type, DateTime)
    ]


def test_存在时间列() -> None:
    """防止上面的收集逻辑失效后，下面那条断言变成空跑通过。"""
    assert len(_datetime_columns()) >= 20


def test_所有时间列都带时区() -> None:
    naive = [
        f"{table}.{column}" for table, column, type_ in _datetime_columns() if not type_.timezone
    ]
    assert not naive, f"这些列会丢时区，必须用 timestamptz: {naive}"


def test_基类全局映射了_datetime() -> None:
    """逐个模型显式写 DateTime(timezone=True) 漏一处不会报错，所以在基类统一配。"""
    mapped = Base.type_annotation_map
    from datetime import datetime

    assert datetime in mapped
    configured = mapped[datetime]
    assert isinstance(configured, DateTime)
    assert configured.timezone
