# Final Gold v3（裁决冻结版）

本目录由两份独立标注工作簿和 161 条专业裁决记录通过 `analytics.pipelines.gold_annotation_v3 finalize` 生成。

- `final_event_gold_v3.csv`：120 条事件语义金标，其中 47 条来自裁决。
- `final_body_fact_gold_v3.csv`：60 条正文事实金标，其中 29 条来自裁决。
- `final_graph_relevance_gold_v3.csv`：180 条 Graph RAG 相关性金标，其中 85 条来自裁决。
- `final_gold_manifest.json`：源工作簿、裁决文件和三个金标文件的 SHA-256 清单。
- `quality_report.json`：质量中心 API 与前端的只读数据源。

360 条标签均已冻结。由于 `G3-E061` 与 `G3-B053` 的原文不可提取且原始置信度较低，两条记录保留在最终金标中供审计，但系统离线指标默认只使用其余 358 条可评测记录。

完成裁决只表示最终标签已就绪，不等于 Graph RAG 已通过放量门禁；系统仍需在这批金标上产出 Recall@K、MRR、引用正确率和权限泄漏结果。

首次系统基准已经生成：Graph RAG Recall@5=0.7832、MRR=0.8367、NDCG@5=0.8088、
Top-1=0.6667，81 条对抗诱饵的权限/证券/未来信息泄漏均为 0。由于 Recall@5 和 Top-1
未达到冻结门槛，Graph RAG 继续受控关闭。完整报告位于
`analytics/experiments/20260826-graph-rag-final-gold-v3/graph_rag_benchmark.json`。
