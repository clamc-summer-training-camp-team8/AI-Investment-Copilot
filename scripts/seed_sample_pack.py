"""导入业务样例包到本地库，用于联调与演示。

样例包路径由 app.core.config.settings.sample_pack_dir 给出。

三条不可放松的约定：

1. **全部标记 is_illustrative=True。** 样例包是虚构数据，不构成投资建议。
   混入真实数据集会造成错误结论（DA-AC-08）。
2. **先写指标别名再导观测值。** 交付包存在两套命名：指标字典用 MET-001~005，
   台账与样例 CSV 用 MET-DEMO-001~003。不先解析别名，假设—指标映射会断链。
3. **时间显式声明时区。** CSV/JSON 为业务时区，台账 xlsx 为 naive UTC，
   两者相差 8 小时。naive datetime 会被 app.core.timeutil.ensure_aware 拒绝。

用法：
    make seed                       # 等价于下面这条
    python -m scripts.seed_sample_pack
    python -m scripts.seed_sample_pack --dry-run    # 只解析不写库
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.timeutil import BUSINESS_TZ, ensure_aware
from app.db.models import (
    Document,
    Event,
    MetricAlias,
    MetricObservation,
    Security,
)
from app.db.session import session_scope

DEMO_SECURITY_ID = "DEMO001"
DEMO_SECURITY_NAME = "华夏储能科技（虚拟）"

# 指标字典与台账/CSV 的两套命名对照。别名必须先落库，否则假设—指标映射断链。
METRIC_ALIASES: dict[str, str] = {
    "MET-DEMO-001": "MET-001",
    "MET-DEMO-002": "MET-002",
    "MET-DEMO-003": "MET-003",
}

METRIC_CSV = "样例指标历史数据.csv"
EVENT_CSV = "样例事件人工标注.csv"
RESEARCH_TXT = "样例投研资料.txt"

DATA_VERSION = "sample-pack-v1.0"


@dataclass(frozen=True)
class ParsedPack:
    """解析结果。--dry-run 时只产出这个对象，不触库。"""

    documents: list[Document]
    observations: list[MetricObservation]
    events: list[Event]

    def summary(self) -> str:
        return (
            f"文档 {len(self.documents)} 篇 / "
            f"观测值 {len(self.observations)} 条 / "
            f"事件 {len(self.events)} 条"
        )


def _read_csv(path: Path) -> list[dict[str, str]]:
    """样例 CSV 带 BOM，用 utf-8-sig 读，否则首列键名会带 \\ufeff。"""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _dec(value: str | None) -> Decimal | None:
    value = (value or "").strip()
    return Decimal(value) if value else None


def _business_dt(value: str) -> datetime:
    """解析业务时区时间。CSV 里既有 'YYYY-MM-DD HH:MM' 也有纯日期。"""
    text = value.strip()
    fmt = "%Y-%m-%d %H:%M" if " " in text else "%Y-%m-%d"
    return ensure_aware(datetime.strptime(text, fmt), assume=BUSINESS_TZ)


def _business_date(value: str) -> date:
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def parse_documents(pack_dir: Path) -> list[Document]:
    """从样例投研资料解析文档。

    行格式：``[DOC-DEMO-001 | 内部研究摘要 | 2026-01-15 09:00]`` 后跟正文段落。
    published_at 取标题行的时间，是收益标签的时间起点（FLD-002），不能用入库时间代替。
    """
    text = (pack_dir / RESEARCH_TXT).read_text(encoding="utf-8")
    documents: list[Document] = []
    header: tuple[str, str, str] | None = None

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]") and line.count("|") == 2:
            doc_id, doc_type, published = (part.strip() for part in line[1:-1].split("|"))
            header = (doc_id, doc_type, published)
            continue
        if header is None or not line:
            continue

        doc_id, doc_type, published = header
        documents.append(
            Document(
                document_id=doc_id,
                title=f"{doc_type} {doc_id}",
                doc_type=doc_type,
                security_id=DEMO_SECURITY_ID,
                published_at=_business_dt(published),
                content_hash=_content_hash(line),
                parser_version="sample-v1",
                body=line,
                visibility_label="内部受限",
                is_illustrative=True,
            )
        )
        header = None

    return documents


def _content_hash(body: str) -> str:
    """SHA-256，对应 FLD-003 的去重与版本追踪字段。"""
    return sha256(body.encode("utf-8")).hexdigest()


def parse_observations(pack_dir: Path) -> list[MetricObservation]:
    """指标观测值。metric_id 落库前统一解析为指标字典的正式 ID。"""
    rows = _read_csv(pack_dir / METRIC_CSV)
    return [
        MetricObservation(
            security_id=row["security_id"],
            metric_id=METRIC_ALIASES.get(row["metric_id"], row["metric_id"]),
            metric_version="v1.0",
            period=row["period"],
            period_type="单季度",
            observation_date=_business_date(row["observation_date"]),
            actual_value=_dec(row.get("actual_value")),
            raw_value=row.get("actual_value"),
            unit=row["unit"],
            expected_value=_dec(row.get("expected_value")),
            benchmark_value=_dec(row.get("benchmark_value")),
            source_document_id=row.get("source_document_id") or None,
            data_version=DATA_VERSION,
            is_illustrative=True,
        )
        for row in rows
    ]


def parse_events(pack_dir: Path) -> list[Event]:
    """结构化事件。

    occurred_on 与 disclosure_time 分开存储：前者是事实发生时间，后者是首次公开
    可得时间（FLD-006）。合成一个字段会让 DQ-003 的泄露判定失去依据。
    """
    rows = _read_csv(pack_dir / EVENT_CSV)
    return [
        Event(
            event_id=row["event_id"],
            document_id=row.get("document_id") or None,
            security_id=row.get("security_id") or None,
            event_type=row["event_type"],
            summary=row["evidence"],
            occurred_on=_business_date(row["event_time"]),
            disclosure_time=_business_dt(row["disclosure_time"]),
            fingerprint=_content_hash(f"{row['event_id']}|{row['evidence']}"),
            source_document_ids=[row["document_id"]] if row.get("document_id") else None,
            version="v1.0",
            is_illustrative=True,
        )
        for row in rows
    ]


def parse_pack(pack_dir: Path) -> ParsedPack:
    return ParsedPack(
        documents=parse_documents(pack_dir),
        observations=parse_observations(pack_dir),
        events=parse_events(pack_dir),
    )


def load(session: Session, pack: ParsedPack) -> None:
    """写库。顺序固定：证券 → 别名 → 文档 → 观测值 → 事件。

    别名必须早于观测值：观测值的 metric_id 已按别名表归一，若别名表缺失，
    后续按指标字典查口径会查不到记录。
    """
    session.merge(
        Security(
            security_id=DEMO_SECURITY_ID,
            name=DEMO_SECURITY_NAME,
            industry="电力设备（虚拟）",
            is_illustrative=True,
        )
    )
    for alias, metric_id in METRIC_ALIASES.items():
        session.merge(
            MetricAlias(alias=alias, metric_id=metric_id, source_note="业务样例包与台账命名")
        )
    session.flush()

    for document in pack.documents:
        session.merge(document)
    session.flush()

    for observation in pack.observations:
        session.add(observation)
    for event in pack.events:
        session.merge(event)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导入业务样例包（全部虚构演示数据）")
    parser.add_argument("--dry-run", action="store_true", help="只解析并打印统计，不写库")
    args = parser.parse_args(argv)

    pack_dir = settings.sample_pack_dir
    if not pack_dir.is_dir():
        print(f"样例包目录不存在: {pack_dir}", file=sys.stderr)
        return 1

    pack = parse_pack(pack_dir)
    print(f"解析完成：{pack.summary()}")

    if args.dry_run:
        print("--dry-run 未写库")
        return 0

    with session_scope() as session:
        load(session, pack)

    print("导入完成。全部记录 is_illustrative=True，禁止用于真实投资结论。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
