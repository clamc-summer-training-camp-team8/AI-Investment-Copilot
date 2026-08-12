"""复核中心路由（PRD 6.1 一级导航之一）。

当前只提供裁决队列的**读**接口。队列内容是两位标注者对同一条公告的方向判断不一致的
样本，需要业务导师裁决。

为什么这个队列重要：三行业九公司的评测里，医药方向一致率只有 30.7%、标注者方向
kappa 0.50，而假设 kappa 是 1.0——分歧全部集中在方向，不在关联。根因是「拿到临床
试验批件算不算支持需求假设的证据」没有业务共识（恒瑞两年多有 200+ 条批件公告，
单条对短期基本面影响接近于零，规则却一律判为支持）。这不是标注失误也不是实现缺陷，
只能由导师裁决。471 条里恒瑞占 316 条。

裁决结果的**写**接口留到下一步：写入要落库、留痕、并产出独立于抽取规则的人工金标，
那是评测基准的一部分，不能和只读查询混在一个改动里。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import ActorDep, UowDep
from app.core.config import PROJECT_ROOT
from app.core.domain import AdjudicationDecisionRecord
from app.schemas.thesis import (
    AdjudicationDecisionIn,
    AdjudicationOut,
    AdjudicationPage,
    PageMeta,
)
from app.services import adjudication as adjudication_service
from app.services import query as query_service
from app.services.errors import ValidationFailed

router = APIRouter(tags=["reviews"])

QUEUE_PATH = PROJECT_ROOT / "real_data" / "dataset" / "adjudication_queue.csv"


@dataclass(frozen=True)
class QueueRow:
    event_id: str
    company: str
    title: str
    category: str
    annotator_a_hypothesis: str
    annotator_a_direction: str
    annotator_b_hypothesis: str
    annotator_b_direction: str

    @property
    def disagreement(self) -> str:
        """分歧类型。当前队列全部是方向分歧（假设 kappa = 1.0）。"""
        parts = []
        if self.annotator_a_hypothesis != self.annotator_b_hypothesis:
            parts.append("假设")
        if self.annotator_a_direction != self.annotator_b_direction:
            parts.append("方向")
        return "、".join(parts) or "无分歧"


@lru_cache(maxsize=1)
def _load_queue() -> tuple[QueueRow, ...]:
    """读队列文件。

    带缓存：文件是构建产物、进程内不会变，每次请求重读 471 行没有意义。
    文件缺失返回空队列而不是抛错——数据集是可选的构建产物，没有它接口应该
    返回空列表，而不是让整个复核中心 500。
    """
    if not QUEUE_PATH.exists():
        return ()
    with QUEUE_PATH.open(encoding="utf-8") as fh:
        return tuple(
            QueueRow(
                event_id=row["event_id"],
                company=row["company"],
                title=row["title"],
                category=row["category"],
                annotator_a_hypothesis=row["annotator_a_hypothesis"],
                annotator_a_direction=row["annotator_a_direction"],
                annotator_b_hypothesis=row["annotator_b_hypothesis"],
                annotator_b_direction=row["annotator_b_direction"],
            )
            for row in csv.DictReader(fh)
        )


@router.get("/reviews/adjudications", response_model=AdjudicationPage)
def list_adjudications(
    actor: ActorDep,
    uow: UowDep,
    company: Annotated[str | None, Query(description="按公司过滤")] = None,
    category: Annotated[str | None, Query(description="按公告类别过滤")] = None,
    limit: Annotated[int, Query(ge=1, le=query_service.MAX_LIMIT)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AdjudicationPage:
    """待裁决样本列表。

    两位标注者的判断原样返回，不给「系统建议」：给了会让导师倾向于跟随而不是判断，
    而这个队列存在的目的恰恰是取得独立于规则的人工判断。
    """
    rows = _load_queue()
    if company:
        rows = tuple(r for r in rows if r.company == company)
    if category:
        rows = tuple(r for r in rows if r.category == category)

    window = rows[offset : offset + limit]
    return AdjudicationPage(
        items=[_out(r, uow.adjudications.get(r.event_id)) for r in window],
        page=PageMeta(total=len(rows), limit=limit, offset=offset),
    )


def _out(row: QueueRow, decision: AdjudicationDecisionRecord | None) -> AdjudicationOut:
    return AdjudicationOut(
        event_id=row.event_id,
        company=row.company,
        title=row.title,
        category=row.category,
        annotator_a_hypothesis=row.annotator_a_hypothesis,
        annotator_a_direction=row.annotator_a_direction,
        annotator_b_hypothesis=row.annotator_b_hypothesis,
        annotator_b_direction=row.annotator_b_direction,
        disagreement=row.disagreement,
        resolved=decision is not None,
        decided_hypothesis=decision.hypothesis if decision else None,
        decided_direction=decision.direction if decision else None,
        decision_reason=decision.reason if decision else None,
        decided_by=decision.decided_by if decision else None,
        decided_at=decision.decided_at if decision else None,
    )


@router.post("/reviews/adjudications/{event_id}", response_model=AdjudicationOut)
def decide_adjudication(
    event_id: str,
    payload: AdjudicationDecisionIn,
    actor: ActorDep,
    uow: UowDep,
) -> AdjudicationOut:
    row = next((item for item in _load_queue() if item.event_id == event_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="待裁决样本不存在")
    try:
        decision = adjudication_service.decide(
            uow,
            event_id=event_id,
            hypothesis=payload.hypothesis,
            direction=payload.direction,
            reason=payload.reason,
            actor=actor,
        )
    except ValidationFailed as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _out(row, decision)
