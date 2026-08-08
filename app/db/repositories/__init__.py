"""仓储实现。SQL 只出现在这一层。

`build_uow` 把一个 Session 组装成服务层要的 UnitOfWork。所有仓储共用同一个
Session，因此业务写入与审计写入天然在同一事务里——审计失败会让业务动作一起
回滚，这是 FR-A-003 可追溯性的前提。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.domain import UnitOfWork
from app.db.repositories.evidence import (
    SqlAuditRepo,
    SqlEvidenceRepo,
    SqlObservationRepo,
    SqlSuggestionRepo,
    SqlVersionRepo,
)
from app.db.repositories.thesis import SqlThesisRepo

__all__ = [
    "SqlAuditRepo",
    "SqlEvidenceRepo",
    "SqlObservationRepo",
    "SqlSuggestionRepo",
    "SqlThesisRepo",
    "SqlVersionRepo",
    "build_uow",
]


def build_uow(session: Session) -> UnitOfWork:
    return UnitOfWork(
        thesis=SqlThesisRepo(session),
        evidence=SqlEvidenceRepo(session),
        observations=SqlObservationRepo(session),
        suggestions=SqlSuggestionRepo(session),
        versions=SqlVersionRepo(session),
        audit=SqlAuditRepo(session),
    )
