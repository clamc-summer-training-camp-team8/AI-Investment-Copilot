"""Import reviewed public-source fact sheets as candidate, not confirmed, knowledge objects."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.core.config import PROJECT_ROOT
from app.db.models.assets import DocumentSecurityRelation
from app.db.models.core import Document, DocumentSegment, Event, Evidence, Hypothesis, Thesis
from app.db.session import session_scope


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}-{hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]}"


def _latest_hypothesis(
    session,
    *,
    security_id: str,
    target: str,
    published_at: datetime,
    allow_historical_baseline: bool = False,
) -> Hypothesis:
    row = session.scalar(
        select(Hypothesis)
        .join(Thesis, Thesis.thesis_id == Hypothesis.thesis_id)
        .where(
            Thesis.security_id == security_id,
            Thesis.established_on <= published_at.date(),
            Hypothesis.name == target,
        )
        .order_by(Thesis.established_on.desc())
        .limit(1)
    )
    if row is None and allow_historical_baseline:
        row = session.scalar(
            select(Hypothesis)
            .join(Thesis, Thesis.thesis_id == Hypothesis.thesis_id)
            .where(Thesis.security_id == security_id, Hypothesis.name == target)
            .order_by(Thesis.established_on.asc())
            .limit(1)
        )
    if row is None:
        raise ValueError(f"{security_id} 在 {published_at.date()} 前没有目标假设：{target}")
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=PROJECT_ROOT / "analytics" / "staging" / "p1-auto-official-source-seed-20260824.json",
    )
    parser.add_argument("--confirm-staged-facts", action="store_true")
    parser.add_argument(
        "--allow-historical-baseline",
        action="store_true",
        help="允许将早于最早主逻辑的官方事实作为该主逻辑的历史基线；默认禁止。",
    )
    args = parser.parse_args()
    if not args.confirm_staged_facts:
        parser.error("导入会写入数据库；请显式传入 --confirm-staged-facts")
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if payload.get("status") != "staged_requires_human_review":
        raise SystemExit("只允许导入 staged_requires_human_review 状态的数据包")

    documents = segments = evidence_count = 0
    with session_scope() as session:
        for record in payload["records"]:
            published_at = datetime.fromisoformat(record["published_at"])
            if published_at.tzinfo is None:
                raise ValueError("published_at 必须包含时区")
            source_url = str(record["source_url"])
            document_id = _stable_id("DOC-STG", source_url)
            content = "\n".join([record["title"], *record["facts"]])
            document = session.get(Document, document_id)
            if document is None:
                document = Document(
                    document_id=document_id,
                    title=record["title"],
                    source_id=payload["dataset_version"],
                    doc_type="official_source_fact_sheet",
                    security_id=record["security_id"],
                    published_at=published_at,
                    content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    parser_version="staged-facts-v1",
                    raw_path=source_url,
                    body=content,
                    visibility_label="公开",
                    is_illustrative=False,
                )
                session.add(document)
                documents += 1
                # 同一来源可同时提供支持与反证；先写入以保证下一条记录可复用该文档。
                session.flush()
            relation = session.scalar(
                select(DocumentSecurityRelation).where(
                    DocumentSecurityRelation.document_id == document_id,
                    DocumentSecurityRelation.security_id == record["security_id"],
                    DocumentSecurityRelation.relation_type == "主体",
                )
            )
            if relation is None:
                # 来源与证券的归属已由本次已复核的数据包显式给出。这个关系
                # 仅控制检索范围，不改变证据的“候选/待确认”状态。
                session.add(
                    DocumentSecurityRelation(
                        document_id=document_id,
                        security_id=record["security_id"],
                        relation_type="主体",
                        status="已确认",
                        confidence=1,
                        created_by="staged-official-source-importer",
                    )
                )
                session.flush()
            locator = f"{document_id}#paragraph-1"
            if session.scalar(select(DocumentSegment).where(DocumentSegment.locator == locator)) is None:
                session.add(
                    DocumentSegment(
                        document_id=document_id,
                        locator=locator,
                        ordinal=1,
                        content=content,
                        content_kind="paragraph",
                        extraction_method="staged",
                    )
                )
                segments += 1
                session.flush()
            event_id = _stable_id("EVT-STG", source_url)
            if session.get(Event, event_id) is None:
                session.add(
                    Event(
                        event_id=event_id,
                        document_id=document_id,
                        security_id=record["security_id"],
                        event_type="经营业绩",
                        summary=record["title"],
                        disclosure_time=published_at,
                        fingerprint=hashlib.sha256(source_url.encode("utf-8")).hexdigest(),
                        version="staged-facts-v1",
                    )
                )
                session.flush()
            for target in record["hypothesis_targets"]:
                hypothesis = _latest_hypothesis(
                    session,
                    security_id=record["security_id"],
                    target=target,
                    published_at=published_at,
                    allow_historical_baseline=args.allow_historical_baseline,
                )
                # 同一公告可能既支持又反驳同一个假设；事实切片和方向都必须
                # 纳入幂等键，避免把反证错误折叠为已存在的支持证据。
                evidence_key = "|".join(
                    [
                        source_url,
                        hypothesis.hypothesis_id,
                        record["evidence_direction"],
                        record["title"],
                        "\n".join(record["facts"]),
                    ]
                )
                evidence_id = _stable_id("EVD-STG", evidence_key)
                # 兼容旧版幂等键：在查新 ID 之外，按业务语义确认同一证据是否
                # 已经入库，避免升级脚本后重复导入历史 staged 包。
                existing_evidence = session.scalar(
                    select(Evidence).where(
                        Evidence.source_url == source_url,
                        Evidence.hypothesis_id == hypothesis.hypothesis_id,
                        Evidence.direction == record["evidence_direction"],
                        Evidence.fact_excerpt == "；".join(record["facts"]),
                        Evidence.source_document_title == record["title"],
                    )
                )
                if session.get(Evidence, evidence_id) is not None or existing_evidence is not None:
                    continue
                session.add(
                    Evidence(
                        evidence_id=evidence_id,
                        security_id=record["security_id"],
                        event_id=event_id,
                        thesis_id=hypothesis.thesis_id,
                        hypothesis_id=hypothesis.hypothesis_id,
                        evidence_type="经营事实",
                        direction=record["evidence_direction"],
                        strength="强",
                        strength_score=0.8,
                        horizon="中期",
                        is_direct=True,
                        evidence_locator=locator,
                        transmission_path="官方披露→待确认事实切片→假设候选证据",
                        fact_excerpt="；".join(record["facts"]),
                        source_document_id=document_id,
                        source_document_title=record["title"],
                        disclosed_at=published_at,
                        source_url=source_url,
                        ai_status="候选",
                        ai_confidence=0.8,
                        model_version="gpt-5.6-terra-offline",
                        prompt_version="staged-source-v1",
                        confirmation_status="待确认",
                        review_note=record["review_note"],
                    )
                )
                evidence_count += 1
    print(json.dumps({"documents": documents, "segments": segments, "candidate_evidence": evidence_count}, ensure_ascii=False))


if __name__ == "__main__":
    main()
