from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.embeddings import embed_text
from app.core.domain import SegmentEmbeddingRecord
from app.db.repositories.assets import SqlAssetRepo


def test_pgvector_extension_and_permission_first_hybrid_search(session: Session) -> None:
    assert session.scalar(text("select extversion from pg_extension where extname='vector'"))
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    public_doc, secret_doc = f"DOC-VEC-P-{suffix}", f"DOC-VEC-S-{suffix}"
    session.execute(
        text(
            """INSERT INTO document
               (document_id,title,published_at,content_hash,parser_version,visibility_label,is_illustrative)
               VALUES (:public_doc,'公开',now(),:public_hash,'v1','公开',false),
                      (:secret_doc,'机密',now(),:secret_hash,'v1','机密',false)"""
        ),
        {
            "public_doc": public_doc,
            "secret_doc": secret_doc,
            "public_hash": ("a" + suffix)[:64].ljust(64, "a"),
            "secret_hash": ("b" + suffix)[:64].ljust(64, "b"),
        },
    )
    session.execute(
        text(
            """INSERT INTO segment_search_index
               (index_id,document_id,locator,content,visibility_label,search_vector)
               VALUES (:public_index,:public_doc,:public_locator,'订单显著增长','公开',to_tsvector('simple','订单显著增长')),
                      (:secret_index,:secret_doc,:secret_locator,'订单显著增长并含机密预测','机密',to_tsvector('simple','订单显著增长并含机密预测'))"""
        ),
        {
            "public_index": f"IDX-P-{suffix}",
            "secret_index": f"IDX-S-{suffix}",
            "public_doc": public_doc,
            "secret_doc": secret_doc,
            "public_locator": f"{public_doc}#paragraph-1",
            "secret_locator": f"{secret_doc}#paragraph-1",
        },
    )
    repo = SqlAssetRepo(session)
    vector = embed_text("订单增长")
    assert (
        repo.upsert_embeddings(
            [
                SegmentEmbeddingRecord(
                    f"IDX-P-{suffix}",
                    None,
                    public_doc,
                    f"{public_doc}#paragraph-1",
                    "hash-char-2gram-v1",
                    vector,
                ),
                SegmentEmbeddingRecord(
                    f"IDX-S-{suffix}",
                    None,
                    secret_doc,
                    f"{secret_doc}#paragraph-1",
                    "hash-char-2gram-v1",
                    vector,
                ),
            ]
        )
        == 2
    )
    hits = repo.hybrid_search_segments(
        query="订单增长",
        query_embedding=vector,
        embedding_version="hash-char-2gram-v1",
        visibility_labels=("公开",),
        security_ids=(),
        industries=(),
        published_from=None,
        published_to=None,
        keyword_weight=0.45,
        vector_weight=0.55,
        limit=10,
    )
    returned = [hit.document_id for hit in hits]
    assert public_doc in returned
    assert secret_doc not in returned
    assert all(hit.visibility_label == "公开" for hit in hits)
    assert all(hit.embedding_version == "hash-char-2gram-v1" for hit in hits)
