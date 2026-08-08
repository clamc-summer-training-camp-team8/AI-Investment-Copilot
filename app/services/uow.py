"""事务边界工厂。

存在的理由是分层：`app/api` 不允许 import `app/db`（`.importlinter` 强制），
但它需要一个带事务的 UnitOfWork。让服务层提供工厂，api 只依赖服务层。

import 放在函数内部而不是模块顶层：模块级 import 会让 `app.services` 在被导入
时就连数据库，纯函数的单元测试也要起库。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from app.core.domain import UnitOfWork


@contextmanager
def uow_scope() -> Iterator[UnitOfWork]:
    """一个事务内的仓储集合。异常回滚，正常提交。

    业务写入与审计写入共用这个事务，审计失败会让业务动作一起回滚
    （FR-A-003 可追溯性的前提）。
    """
    from app.db.repositories import build_uow
    from app.db.session import session_scope

    with session_scope() as session:
        yield build_uow(session)
