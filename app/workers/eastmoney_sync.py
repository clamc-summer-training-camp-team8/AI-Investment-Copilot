"""每日东方财富资料同步：采集后交给现有文档链和 Graph RAG。"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from app.core.config import settings
from app.ingest.eastmoney import EastmoneyAdapter, EastmoneyDocument


async def sync_eastmoney_daily_job(ctx: dict[str, Any]) -> dict[str, Any]:
    """按环境配置的证券列表抓取四个栏目，并投递到文档处理链。

    未配置证券或接口地址时返回明确的 skipped，不写入任何模拟数据。
    ``EASTMONEY_ENDPOINTS`` 为 JSON 对象，键可为 news/announcements/
    research_reports/post，值为包含 ``{security_id}`` 的 URL 模板。
    """
    security_ids = [item.strip() for item in os.getenv("EASTMONEY_SECURITY_IDS", "").split(",") if item.strip()]
    if not security_ids:
        return {"ok": True, "stage": "skipped", "reason": "未配置 EASTMONEY_SECURITY_IDS", "queued": 0}
    try:
        endpoints = json.loads(os.getenv("EASTMONEY_ENDPOINTS", "{}"))
    except json.JSONDecodeError as exc:
        return {"ok": False, "stage": "failed", "reason": f"EASTMONEY_ENDPOINTS 配置无效: {exc}", "queued": 0}

    adapter = EastmoneyAdapter(endpoint_templates=endpoints)
    categories = ("news", "announcements", "research_reports", "post")
    documents: list[EastmoneyDocument] = []
    for security_id in security_ids:
        for category in categories:
            fetcher = getattr(adapter, f"fetch_{category}")
            documents.extend(await asyncio.to_thread(fetcher, security_id))

    queued = 0
    upload_dir = (settings.storage_dir / "uploads" / "eastmoney").resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)
    redis = ctx.get("redis")
    if redis is None:
        return {"ok": False, "stage": "failed", "reason": "Redis worker 不可用", "queued": 0}
    for document in documents:
        if not document.body:
            if not document.attachment_url:
                continue
            document = await asyncio.to_thread(
                adapter.parse_attachment,
                security_id=document.security_id,
                category=document.category,
                title=document.title,
                attachment_url=document.attachment_url,
                published_at=document.published_at,
            )
        digest = document.content_hash[:24]
        document_id = f"EM-{digest}"
        path = upload_dir / f"{document_id}.txt"
        path.write_text(document.body, encoding="utf-8")
        job_id = f"eastmoney:{document_id}"
        await redis.enqueue_job(
            "process_document_job",
            {
                "document_id": document_id,
                "job_id": job_id,
                "path": str(path),
                "source_filename": f"{document.title}.txt",
                "published_at": document.published_at.isoformat() if document.published_at else None,
                "security_id": document.security_id,
                "actor_id": "eastmoney-sync",
                "source_url": document.source_url,
                "source_id": "eastmoney",
            },
            _job_id=job_id,
        )
        queued += 1
    return {"ok": True, "stage": "queued", "fetched": len(documents), "queued": queued}
