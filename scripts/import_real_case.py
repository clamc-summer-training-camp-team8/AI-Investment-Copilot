"""将人工核验后的真实公开案例导入本地联调库。

真实文件固定放在 real_data/real_case_sg.json，不提交到仓库。脚本仅处理显式
提供的公开来源字段，避免把样例包或模型生成内容误标为真实案例。
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from app.core.config import PROJECT_ROOT
from app.db.models.core import Document, Evidence, Hypothesis, Security, Thesis
from app.db.session import session_scope

DATA_FILE = PROJECT_ROOT / "real_data" / "real_case_sg.json"
REQUIRED_EVIDENCE = {
    "evidence_id",
    "hypothesis_id",
    "evidence_type",
    "direction",
    "evidence_locator",
    "fact_excerpt",
    "source_document_id",
    "source_document_title",
    "disclosed_at",
    "source_url",
}


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("disclosed_at 必须包含时区，例如 +08:00")
    return parsed


def main() -> None:
    if not DATA_FILE.is_file():
        template = PROJECT_ROOT / "scripts" / "templates" / "real_case_sg.template.json"
        raise SystemExit(f"缺少 {DATA_FILE}；请复制并填写模板 {template}")

    payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    security = payload["security"]
    thesis = payload["thesis"]
    evidences = payload["evidences"]
    if not evidences:
        raise ValueError("真实案例至少需要一条证据")

    with session_scope() as session:
        session.merge(Security(**security, is_illustrative=False))
        session.merge(
            Thesis(
                **thesis,
                owner="示例研究员",
                status="验证中",
                version=1,
                is_illustrative=False,
            )
        )
        for item in payload["hypotheses"]:
            session.merge(Hypothesis(**item, thesis_id=thesis["thesis_id"], status="待验证"))

        for item in evidences:
            missing = REQUIRED_EVIDENCE - item.keys()
            if missing:
                raise ValueError(f"证据缺少字段：{sorted(missing)}")
            if not item["source_url"].startswith("https://"):
                raise ValueError("真实案例 source_url 必须为 https 公开链接")
            document_id = item["source_document_id"]
            excerpt = item["fact_excerpt"]
            session.merge(
                Document(
                    document_id=document_id,
                    title=item["source_document_title"],
                    published_at=_datetime(item["disclosed_at"]),
                    content_hash=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                    raw_path=item["source_url"],
                    body=excerpt,
                    visibility_label="公开",
                    is_illustrative=False,
                )
            )
            session.merge(
                Evidence(
                    evidence_id=item["evidence_id"],
                    security_id=security["security_id"],
                    thesis_id=thesis["thesis_id"],
                    hypothesis_id=item["hypothesis_id"],
                    event_id=None,
                    evidence_type=item["evidence_type"],
                    direction=item["direction"],
                    evidence_locator=item["evidence_locator"],
                    fact_excerpt=excerpt,
                    source_document_id=document_id,
                    source_document_title=item["source_document_title"],
                    disclosed_at=_datetime(item["disclosed_at"]),
                    occurred_at=(date.fromisoformat(item["occurred_at"]) if item.get("occurred_at") else None),
                    source_url=item["source_url"],
                    strength=item.get("strength"),
                    ai_status=item.get("ai_status"),
                    ai_confidence=Decimal(item["ai_confidence"]) if item.get("ai_confidence") else None,
                    model_version=item.get("model_version"),
                    prompt_version=item.get("prompt_version"),
                    confirmation_status="待确认",
                    review_status="待复核",
                )
            )
    print(f"真实案例已导入：{thesis['thesis_id']}，证据 {len(evidences)} 条")


if __name__ == "__main__":
    main()
