"""将已提交的行业公开数据集导入本地 PostgreSQL 联调库。

脚本只读取 ``real_data/`` 中已纳入版本控制的公开数据：公告标题、披露时间、
原文 URL、财务指标和人工双标注结果。公告正文不在数据包内，因此证据摘录只使用
来源数据中逐字保存的公告标题；研究员可通过 ``source_url`` 回到公开原文核验。

重复执行是安全的：主键固定，已有记录会按同一公开数据版本更新，不会生成重复数据。
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from app.core.config import PROJECT_ROOT
from app.db.models.core import (
    Document,
    DocumentSegment,
    Event,
    Evidence,
    EvidenceRelation,
    Hypothesis,
    HypothesisMetricMap,
    Metric,
    MetricObservation,
    Security,
    Thesis,
)
from app.db.session import session_scope

DATA_ROOT = PROJECT_ROOT / "real_data"
DATASET_ROOT = DATA_ROOT / "dataset"
RAW_ROOT = DATA_ROOT / "raw"

# HTTP 请求头按 ASCII 传输；本地代理注入的身份必须与这里的归属一致。
OWNER = "analyst-mvp"
TEAM = "equity-research"
ANNOUNCEMENT_VERSION = "cninfo-announcement-v2"
FINANCIAL_VERSION = "em-f10-gincome-v2"

_DIRECTION_MAP = {
    "higher_better": "越高越好",
    "lower_better": "越低越好",
}
_HYPOTHESIS_TYPE = {"H1": "经营", "H2": "盈利", "H3": "公司竞争力"}
_HYPOTHESIS_NAME = {
    "H1": "需求与出货",
    "H2": "盈利质量",
    "H3": "产能与扩张",
}


def _read_json(path: Path) -> object:
    """统一以 UTF-8 读取已提交的数据文件。"""
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_datetime(value: str) -> datetime:
    """公告披露时间必须保留时区，避免把未来信息提前暴露给逻辑。"""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"披露时间缺少时区：{value}")
    return parsed


def _document_id(event_id: str) -> str:
    return f"DOC-{event_id}"


def _evidence_id(event_id: str) -> str:
    return f"EVD-{event_id}"


def _source_hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _hypothesis_code(label: str) -> str | None:
    """将标注集的 H1/H2/H3 标签映射到同季度逻辑的具体假设。"""
    # 标注集是「H1-需求与出货」，逻辑 ID 则是「THS-...-H1-需求与出货」。
    # 两种来源都要取到相同的 H1/H2/H3 编号，不能只按第一个连字符切分。
    matched = re.search(r"(?:^|-)H([123])(?:-|$)", label)
    return f"H{matched.group(1)}" if matched else None


def _latest_thesis_before(
    theses_by_security: dict[str, list[dict]], security_id: str, disclosed_at: datetime
) -> dict | None:
    """取公告首次公开时已经建立的最新逻辑，禁止关联到未来才建立的逻辑。"""
    available = [
        thesis
        for thesis in theses_by_security.get(security_id, [])
        if date.fromisoformat(thesis["established_on"]) <= disclosed_at.date()
    ]
    return max(available, key=lambda thesis: thesis["established_on"], default=None)


def _seed_metrics(session) -> None:
    """指标字典与财务数据口径固定为两个可验证指标。"""
    session.merge(
        Metric(
            metric_id="MET-001",
            version="v1.0",
            name="营业收入同比",
            category="经营",
            definition="单季度营业收入同比增速",
            unit="%",
            frequency="季度",
            period_type="单季度",
            source_id=FINANCIAL_VERSION,
            expected_direction="越高越好",
            status="已确认",
        )
    )
    session.merge(
        Metric(
            metric_id="MET-002",
            version="v1.0",
            name="毛利率",
            category="盈利",
            definition="（营业收入－营业成本）/ 营业收入",
            unit="%",
            frequency="季度",
            period_type="单季度",
            source_id=FINANCIAL_VERSION,
            expected_direction="越高越好",
            status="已确认",
        )
    )


def _seed_theses(session, theses: list[dict]) -> tuple[dict[str, list[dict]], dict[str, dict[str, str]]]:
    """导入证券、逻辑、假设和假设—指标映射。"""
    theses_by_security: dict[str, list[dict]] = defaultdict(list)
    hypothesis_ids: dict[str, dict[str, str]] = {}
    for spec in theses:
        security_id = spec["security_id"]
        theses_by_security[security_id].append(spec)
        session.merge(
            Security(
                security_id=security_id,
                name=spec["company"],
                ticker=security_id,
                industry=spec["industry"],
                aliases=[spec["company"]],
                is_illustrative=False,
            )
        )
        session.merge(
            Thesis(
                thesis_id=spec["thesis_id"],
                security_id=security_id,
                title=spec["title"][:120],
                direction="观察",
                core_view=spec["core_view"],
                established_on=date.fromisoformat(spec["established_on"]),
                horizon_end_on=date.fromisoformat(spec["horizon_end"]),
                owner=OWNER,
                visibility="团队",
                team=TEAM,
                status="验证中",
                version=1,
                invalidation_require_all=bool(spec["invalidation_require_all"]),
                is_illustrative=False,
            )
        )
        # merge 的对象之间没有 ORM relationship；先 flush 才能满足 Hypothesis 的外键。
        session.flush()
        hypothesis_ids[spec["thesis_id"]] = {}
        for item in spec["hypotheses"]:
            code = _hypothesis_code(item["hypothesis_id"])
            if code:
                hypothesis_ids[spec["thesis_id"]][code] = item["hypothesis_id"]
            session.merge(
                Hypothesis(
                    hypothesis_id=item["hypothesis_id"],
                    thesis_id=spec["thesis_id"],
                    name=_HYPOTHESIS_NAME.get(code or "", item["hypothesis_id"]),
                    statement=item["content"],
                    hypothesis_type=_HYPOTHESIS_TYPE.get(code or "", "其他"),
                    # 行业数据集的「重要」在当前两档枚举中归为辅助，不扩大正式核心假设范围。
                    importance="核心" if item["importance"] == "核心" else "辅助",
                    expected_direction=_DIRECTION_MAP.get(item.get("direction", "")),
                    invalidation_rule=item.get("invalidation_rule") or None,
                    status="待验证",
                )
            )
            # 同理，映射表直接持有 hypothesis_id，必须先写入假设。
            session.flush()
            if not item.get("metric_id"):
                continue
            session.merge(
                HypothesisMetricMap(
                    mapping_id=f"MAP-{item['hypothesis_id']}",
                    hypothesis_id=item["hypothesis_id"],
                    metric_id=item["metric_id"],
                    metric_version="v1.0",
                    expected_direction=_DIRECTION_MAP.get(item["direction"], "越高越好"),
                    expected_value=Decimal(item["expectation_value"]),
                    expectation_source="行业公开数据集中的逻辑设定",
                    invalidation_threshold=(
                        Decimal(item["threshold"]) if item.get("threshold") else None
                    ),
                    invalidation_rule=item.get("invalidation_rule") or None,
                    confirmation_status="已确认",
                )
            )
    for items in theses_by_security.values():
        items.sort(key=lambda item: item["established_on"])
    return theses_by_security, hypothesis_ids


def _seed_observations(session, financials: dict[str, object]) -> int:
    """导入收入同比与毛利率观测值；同一自然键重复运行时更新而非重复插入。"""
    existing = {
        (row.security_id, row.metric_id, row.period, row.data_version): row
        for row in session.query(MetricObservation).filter(
            MetricObservation.data_version == FINANCIAL_VERSION
        )
    }
    count = 0
    for security_id, rows in financials["metrics"].items():
        for row in rows:
            disclosure_date = row.get("disclosure_date")
            # 无首次公开日期的观测值不能安全进入验证窗口：用报告期末补齐会造成未来泄露。
            if not disclosure_date:
                continue
            for metric_id, value in (
                ("MET-001", row.get("revenue_yoy")),
                ("MET-002", row.get("gross_margin")),
            ):
                if value is None:
                    continue
                key = (security_id, metric_id, row["period"], FINANCIAL_VERSION)
                target = existing.get(key)
                if target is None:
                    target = MetricObservation(
                        security_id=security_id,
                        metric_id=metric_id,
                        metric_version="v1.0",
                        period=row["period"],
                        data_version=FINANCIAL_VERSION,
                    )
                    session.add(target)
                    existing[key] = target
                target.period_type = row["period_type"]
                target.observation_date = date.fromisoformat(disclosure_date)
                target.actual_value = Decimal(str(value))
                target.unit = "%"
                target.is_illustrative = False
                count += 1
    return count


def _seed_events_and_evidence(
    session,
    events: list[dict[str, str]],
    theses_by_security: dict[str, list[dict]],
    hypothesis_ids: dict[str, dict[str, str]],
) -> tuple[int, int]:
    """导入公告索引和已标注候选证据，不伪造公告正文。"""
    evidence_count = 0
    for item in events:
        disclosed_at = _parse_datetime(item["disclosure_time"])
        document_id = _document_id(item["event_id"])
        source_url = item["url"]
        title = item["title"]
        source_text = f"公告标题：{title}"
        content_hash = _source_hash(source_url, title, item["disclosure_time"])
        session.merge(
            Document(
                document_id=document_id,
                title=title,
                source_id=ANNOUNCEMENT_VERSION,
                doc_type=item["category"] or None,
                security_id=item["security_id"],
                published_at=disclosed_at,
                content_hash=content_hash,
                parser_version=ANNOUNCEMENT_VERSION,
                raw_path=source_url,
                # 数据集未保存公告正文；这里保存的仅是逐字来源标题，不能冒充正文。
                body=source_text,
                visibility_label="公开",
                is_illustrative=False,
            )
        )
        # DocumentSegment 的主键是自增 ID，不能用 merge 判断重复；按唯一定位键更新。
        locator = f"{document_id}#paragraph-1"
        segment = (
            session.query(DocumentSegment)
            .filter(
                DocumentSegment.document_id == document_id,
                DocumentSegment.locator == locator,
            )
            .one_or_none()
        )
        if segment is None:
            session.add(
                DocumentSegment(
                    document_id=document_id,
                    locator=locator,
                    ordinal=1,
                    content=source_text,
                )
            )
        else:
            segment.content = source_text
        session.merge(
            Event(
                event_id=item["event_id"],
                document_id=document_id,
                security_id=item["security_id"],
                event_type=item["category"] or "其他",
                summary=title,
                disclosure_time=disclosed_at,
                fingerprint=_source_hash(item["security_id"], source_url),
                source_document_ids=[document_id],
                # Event.version 列长度为 16；完整采集版本保存在 Document.source_id。
                version="v2",
                is_illustrative=False,
            )
        )
        code = _hypothesis_code(item["annotator_a_hypothesis"])
        thesis = _latest_thesis_before(theses_by_security, item["security_id"], disclosed_at)
        if code is None or thesis is None:
            continue
        hypothesis_id = hypothesis_ids[thesis["thesis_id"]].get(code)
        if hypothesis_id is None:
            continue
        direction = item["annotator_a_direction"]
        if direction not in {"支持", "冲突", "中性"}:
            continue
        session.merge(
            Evidence(
                evidence_id=_evidence_id(item["event_id"]),
                security_id=item["security_id"],
                event_id=item["event_id"],
                thesis_id=thesis["thesis_id"],
                hypothesis_id=hypothesis_id,
                evidence_type="事件",
                direction=direction,
                strength="中",
                strength_score=Decimal("0.70"),
                horizon="中期",
                is_direct=False,
                evidence_locator=f"{document_id}#paragraph-1",
                # 只使用公开数据集已保存的标题，完整正文通过 source_url 打开核验。
                fact_excerpt=source_text,
                source_document_id=document_id,
                source_document_title=title,
                disclosed_at=disclosed_at,
                source_url=source_url,
                ai_status="候选",
                ai_confidence=Decimal("0.70"),
                model_version="dataset-annotation-v1",
                prompt_version="human-double-label-v1",
                confirmation_status="待确认",
                review_status="通过",
                review_note=(
                    "双标注一致；本地数据包仅保留公告标题，完整原文请通过公开链接核验。"
                ),
            )
        )
        # 新库先跑迁移再导入时没有历史 Evidence 可回填，导入脚本需同时创建初始关联。
        relation_id = f"legacy-{_evidence_id(item['event_id'])}"
        if session.get(EvidenceRelation, relation_id) is None:
            session.add(
                EvidenceRelation(
                    relation_id=relation_id,
                    evidence_id=_evidence_id(item["event_id"]),
                    thesis_id=thesis["thesis_id"],
                    hypothesis_id=hypothesis_id,
                    direction=direction,
                    strength="中",
                    reason="双标注一致；由公开公告索引导入的初始关联。",
                    status="待确认",
                    created_by="dataset-import",
                )
            )
        evidence_count += 1
    return len(events), evidence_count


def main() -> None:
    """执行一次完整、可重复的本地真实数据导入。"""
    theses = _read_json(DATASET_ROOT / "theses.json")
    financials = _read_json(RAW_ROOT / "financials.json")
    with (DATASET_ROOT / "events.csv").open(encoding="utf-8", newline="") as file:
        events = list(csv.DictReader(file))

    if not isinstance(theses, list) or not isinstance(financials, dict):
        raise ValueError("真实数据文件结构不符合预期")

    with session_scope() as session:
        _seed_metrics(session)
        theses_by_security, hypothesis_ids = _seed_theses(session, theses)
        # 后续 Document 以 security_id 为外键；先落库，避免批量 flush 时插入顺序不确定。
        session.flush()
        observation_count = _seed_observations(session, financials)
        event_count, evidence_count = _seed_events_and_evidence(
            session, events, theses_by_security, hypothesis_ids
        )

    print(
        "真实行业数据导入完成："
        f"逻辑 {len(theses)} 条，公告事件 {event_count} 条，"
        f"候选证据 {evidence_count} 条，财务观测 {observation_count} 条。"
    )


if __name__ == "__main__":
    main()
