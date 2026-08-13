"""真实公开数据到 AI/RAG 契约的只读适配层。"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.ai.agents.types import AgentEvent, CandidateHypothesis
from app.ai.retrieval import RetrievalDocument
from app.core.config import PROJECT_ROOT
from app.core.enums import ImpactDirection

REAL_DATA_ROOT = PROJECT_ROOT / "real_data"
_ANNOUNCEMENT_ID_RE = re.compile(r"/(\d+)\.pdf$", re.IGNORECASE)


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _boolean(value: str) -> bool:
    return value.strip().lower() == "true"


def _announcement_id(url: str, fallback: str) -> str:
    match = _ANNOUNCEMENT_ID_RE.search(url)
    return match.group(1) if match else fallback


def map_direction(value: str) -> ImpactDirection:
    """把真实标注集的“削弱”映射到项目契约中的“冲突”。"""
    mapping = {
        "支持": ImpactDirection.SUPPORT,
        "削弱": ImpactDirection.CONFLICT,
        "冲突": ImpactDirection.CONFLICT,
        "中性": ImpactDirection.NEUTRAL,
        "无关": ImpactDirection.IRRELEVANT,
    }
    try:
        return mapping[value]
    except KeyError as exc:
        raise ValueError(f"未知影响方向: {value}") from exc


def map_event_type(category: str) -> str:
    """把数据集细分类映射到 event_impact Schema 的受控枚举。"""
    if category == "订单与合同":
        return "订单"
    if category in {"定期报告", "业绩预告", "产销数据"}:
        return "业绩"
    if category == "集采与准入":
        return "政策"
    return "其他"


@dataclass(frozen=True)
class RealAnnouncement:
    announcement_id: str
    security_id: str
    company: str
    title: str
    disclosure_time: datetime
    url: str
    document_type: str
    market: str
    industry: str

    @property
    def document_id(self) -> str:
        return f"ANN-{self.announcement_id}"

    @property
    def locator(self) -> str:
        # 当前数据只有标题。先使用合法且可回溯的首段 locator，正文到达后再替换。
        return f"{self.document_id}#paragraph-1"

    def to_retrieval_document(self) -> RetrievalDocument:
        return RetrievalDocument(
            document_id=self.document_id,
            security_id=self.security_id,
            locator=self.locator,
            content=self.title,
            published_at=self.disclosure_time,
            visibility_label="公开",
            source="cninfo-title",
        )


@dataclass(frozen=True)
class RealAnnotatedEvent:
    event_id: str
    security_id: str
    company: str
    industry: str
    market: str
    title: str
    disclosure_time: datetime
    disclosure_time_precise: bool
    category: str
    annotator_a_hypothesis: str
    annotator_a_direction: ImpactDirection
    annotator_b_hypothesis: str
    annotator_b_direction: ImpactDirection
    agreed: bool
    needs_adjudication: bool
    split: str
    url: str

    @property
    def announcement_id(self) -> str:
        return _announcement_id(self.url, self.event_id)

    def to_agent_event(self) -> AgentEvent:
        document_id = f"ANN-{self.announcement_id}"
        return AgentEvent(
            event_id=self.event_id,
            document_id=document_id,
            security_id=self.security_id,
            segment_locator=f"{document_id}#paragraph-1",
            segment_text=self.title,
            disclosure_time=self.disclosure_time,
            event_type=map_event_type(self.category),
        )


@dataclass(frozen=True)
class RealThesis:
    thesis_id: str
    security_id: str
    company: str
    quarter: str
    industry: str
    market: str
    title: str
    core_view: str
    candidates: tuple[CandidateHypothesis, ...]


@dataclass(frozen=True)
class RealDataBundle:
    announcements: tuple[RealAnnouncement, ...]
    events: tuple[RealAnnotatedEvent, ...]
    theses: tuple[RealThesis, ...]


def load_announcements(root: Path = REAL_DATA_ROOT) -> tuple[RealAnnouncement, ...]:
    rows = json.loads((root / "raw" / "announcements.json").read_text(encoding="utf-8"))
    return tuple(
        RealAnnouncement(
            announcement_id=str(row["announcement_id"]),
            security_id=str(row["security_id"]),
            company=str(row["company"]),
            title=str(row["title"]),
            disclosure_time=_datetime(str(row["disclosure_time"])),
            url=str(row["url"]),
            document_type=str(row["doc_type"]),
            market=str(row["market"]),
            industry=str(row["industry"]),
        )
        for row in rows
    )


def load_events(root: Path = REAL_DATA_ROOT) -> tuple[RealAnnotatedEvent, ...]:
    with (root / "dataset" / "events.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    return tuple(
        RealAnnotatedEvent(
            event_id=row["event_id"],
            security_id=row["security_id"],
            company=row["company"],
            industry=row["industry"],
            market=row["market"],
            title=row["title"],
            disclosure_time=_datetime(row["disclosure_time"]),
            disclosure_time_precise=_boolean(row["disclosure_time_precise"]),
            category=row["category"],
            annotator_a_hypothesis=row["annotator_a_hypothesis"],
            annotator_a_direction=map_direction(row["annotator_a_direction"]),
            annotator_b_hypothesis=row["annotator_b_hypothesis"],
            annotator_b_direction=map_direction(row["annotator_b_direction"]),
            agreed=_boolean(row["agreed"]),
            needs_adjudication=_boolean(row["needs_adjudication"]),
            split=row["split"],
            url=row["url"],
        )
        for row in rows
    )


def _candidate(thesis_id: str, row: dict[str, Any]) -> CandidateHypothesis:
    return CandidateHypothesis(
        thesis_id=thesis_id,
        hypothesis_id=str(row["hypothesis_id"]),
        statement=str(row["content"]),
    )


def load_theses(root: Path = REAL_DATA_ROOT) -> tuple[RealThesis, ...]:
    rows = json.loads((root / "dataset" / "theses.json").read_text(encoding="utf-8"))
    return tuple(
        RealThesis(
            thesis_id=str(row["thesis_id"]),
            security_id=str(row["security_id"]),
            company=str(row["company"]),
            quarter=str(row["quarter"]),
            industry=str(row["industry"]),
            market=str(row["market"]),
            title=str(row["title"]),
            core_view=str(row["core_view"]),
            candidates=tuple(_candidate(str(row["thesis_id"]), item) for item in row["hypotheses"]),
        )
        for row in rows
    )


def load_real_data(root: Path = REAL_DATA_ROOT) -> RealDataBundle:
    return RealDataBundle(
        announcements=load_announcements(root),
        events=load_events(root),
        theses=load_theses(root),
    )
