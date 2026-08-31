"""对本地正式领域数据执行一次可解释 Graph RAG 查询。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime

from app.ai.graph_rag import GraphRetriever
from app.ai.retrieval import KeywordRetriever, RetrievalQuery
from app.services.graph_rag import build_graph_rag_corpus
from app.services.uow import uow_scope


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行投资研究 Graph RAG 查询")
    parser.add_argument("--thesis-id", required=True, help="用于构建可见图谱的投资逻辑 ID")
    parser.add_argument("--query", required=True, help="研究问题或假设描述")
    parser.add_argument("--as-of", help="ISO 8601 截止时间；禁止召回该时点后的资料")
    parser.add_argument("--visibility", action="append", default=["公开"], help="允许的文档标签")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--max-hops", type=int, default=5)
    parser.add_argument("--include-pending", action="store_true", help="仅限开发诊断；纳入待确认边")
    return parser


def main() -> None:
    args = _parser().parse_args()
    as_of = datetime.fromisoformat(args.as_of) if args.as_of else None
    with uow_scope() as uow:
        thesis = uow.thesis.get(args.thesis_id)
        if thesis is None:
            raise SystemExit(f"投资逻辑不存在: {args.thesis_id}")
        corpus = build_graph_rag_corpus(
            uow,
            thesis_ids=[args.thesis_id],
            include_pending=args.include_pending,
            as_of=as_of,
        )
        retriever = GraphRetriever(
            text_retriever=KeywordRetriever(),
            graph=corpus.graph,
            max_hops=args.max_hops,
            include_unconfirmed_edges=args.include_pending,
        )
        retriever.add(list(corpus.documents))
        result = retriever.search(
            RetrievalQuery(
                text=args.query,
                security_id=thesis.security_id,
                as_of=as_of,
                allowed_visibility=frozenset(args.visibility),
                top_k=args.top_k,
            )
        )
    print(
        json.dumps(
            {
                "retrieval_version": result.retrieval_version,
                "query": args.query,
                "snapshot": {
                    "snapshot_id": corpus.snapshot.snapshot_id,
                    "schema_version": corpus.snapshot.schema_version,
                    "builder_version": corpus.snapshot.builder_version,
                    "vocabulary_version": corpus.snapshot.vocabulary_version,
                    "built_at": corpus.snapshot.built_at.isoformat(),
                    "as_of": corpus.snapshot.as_of.isoformat() if corpus.snapshot.as_of else None,
                    "thesis_ids": corpus.snapshot.thesis_ids,
                    "security_ids": corpus.snapshot.security_ids,
                    "layers": [
                        {
                            "layer": layer.layer.value,
                            "node_count": layer.node_count,
                            "content_hash": layer.content_hash,
                        }
                        for layer in corpus.snapshot.layers
                    ],
                },
                "items": [
                    {
                        "locator": item.locator,
                        "score": item.score,
                        "source": item.source,
                        "content": item.content,
                        "score_components": item.metadata.get("score_components"),
                        "graph_paths": item.metadata.get("graph_paths", []),
                    }
                    for item in result.items
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
