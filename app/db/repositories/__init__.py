"""仓储实现。SQL 只出现在这一层。

`build_uow` 把一个 Session 组装成服务层要的 UnitOfWork。所有仓储共用同一个
Session，因此业务写入与审计写入天然在同一事务里——审计失败会让业务动作一起
回滚，这是 FR-A-003 可追溯性的前提。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.domain import UnitOfWork
from app.db.repositories.adjudication import SqlAdjudicationDecisionRepo
from app.db.repositories.assets import SqlAssetRepo
from app.db.repositories.document import SqlDocumentRepo
from app.db.repositories.evidence import (
    SqlAuditRepo,
    SqlEvidenceFeedRepo,
    SqlEvidenceRelationRepo,
    SqlEvidenceRepo,
    SqlObservationRepo,
    SqlSuggestionRepo,
    SqlVersionRepo,
)
from app.db.repositories.ingestion import SqlDocumentProcessingJobRepo, SqlIngestionReviewRepo
from app.db.repositories.master import SqlEventRepo, SqlSecurityRepo
from app.db.repositories.review import SqlReviewTaskRepo
from app.db.repositories.thesis import SqlMetricRepo, SqlThesisRepo

__all__ = [
    "SqlAdjudicationDecisionRepo",
    "SqlAssetRepo",
    "SqlAuditRepo",
    "SqlDocumentProcessingJobRepo",
    "SqlDocumentRepo",
    "SqlEventRepo",
    "SqlEvidenceFeedRepo",
    "SqlEvidenceRelationRepo",
    "SqlEvidenceRepo",
    "SqlIngestionReviewRepo",
    "SqlMetricRepo",
    "SqlObservationRepo",
    "SqlReviewTaskRepo",
    "SqlSecurityRepo",
    "SqlSuggestionRepo",
    "SqlThesisRepo",
    "SqlVersionRepo",
    "build_uow",
]


def build_uow(session: Session) -> UnitOfWork:
    return UnitOfWork(
        securities=SqlSecurityRepo(session),
        events=SqlEventRepo(session),
        thesis=SqlThesisRepo(session),
        metrics=SqlMetricRepo(session),
        evidence=SqlEvidenceRepo(session),
        relations=SqlEvidenceRelationRepo(session),
        feed=SqlEvidenceFeedRepo(session),
        observations=SqlObservationRepo(session),
        suggestions=SqlSuggestionRepo(session),
        versions=SqlVersionRepo(session),
        audit=SqlAuditRepo(session),
        reviews=SqlReviewTaskRepo(session),
        processing_jobs=SqlDocumentProcessingJobRepo(session),
        ingestion_reviews=SqlIngestionReviewRepo(session),
        documents=SqlDocumentRepo(session),
        adjudications=SqlAdjudicationDecisionRepo(session),
        assets=SqlAssetRepo(session),
    )
