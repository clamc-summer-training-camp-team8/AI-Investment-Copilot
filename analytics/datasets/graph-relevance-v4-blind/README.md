# graph-relevance-v4-blind 交付入口

状态：`ONE_TIME_BLIND_CONSUMED_NOT_READY`

候选池已于 2026-08-26 冻结：30 个新查询、每查询 8 个候选、240 行、9 家公司、195 份不同
公告；v3 查询和候选原文复用均为 0。模型已在标签回收前锁定。专业研究员 `FIN-R01` 已完成
240 行独立标注，唯一一次盲测已于 2026-08-26 消费，结果为 7/12 门禁通过、`rollout_ready=false`。

原始研究员交付件保留在：

- `outputs/Graph-RAG-v4-专业研究员盲标包-20260826/v4_专业研究员独立盲标工作簿_已完成.xlsx`
- `outputs/Graph-RAG-v4-专业研究员盲标包-20260826/README-请先阅读.md`

## 样本要求

- 至少 30 个全新 `查询ID`，不得复用 v3 查询或候选原文作为最终通过证据；
- 每个查询至少 8 个候选，候选须保留公告标题与可核验的关键证据原文；
- `检索截止时间` 必须带时区，候选在该时点应已公开；
- 冻结候选池时不得填写相关性等级、路径判断、理由、标注员或标注时间；
- 研究员标注包和调参包分离。调参人员只接收 `tuner/candidate_pool.csv`。

## 一次性流程

```powershell
python -m analytics.pipelines.graph_relevance_v4 freeze `
  --source analytics/datasets/graph-relevance-v4-blind/query_candidate_pool.csv `
  --output-dir outputs/graph-relevance-v4-blind

# v3 回归调参结束后、回收标签前执行
python -m analytics.pipelines.graph_relevance_v4 lock-model `
  --package-dir outputs/graph-relevance-v4-blind

# 由独立评测人员导入专业研究员回收件
python -m analytics.pipelines.graph_relevance_v4 merge-labels `
  --package-dir outputs/graph-relevance-v4-blind `
  --labels-json X:/restricted/extracted_labels.json `
  --output X:/restricted/graph_relevance_v4_annotated.csv

python -m analytics.pipelines.graph_relevance_v4 finalize `
  --package-dir outputs/graph-relevance-v4-blind `
  --annotated X:/restricted/graph_relevance_v4_annotated.csv `
  --evaluator-dir X:/restricted/graph-relevance-v4-final `
  --researcher-attestation "专业研究员独立阅读原文并完成相关性判断"

# 该命令写入消费回执；无论通过或失败都禁止重复运行
python -m analytics.pipelines.graph_relevance_v4 evaluate-once `
  --evaluator-dir X:/restricted/graph-relevance-v4-final `
  --output analytics/experiments/graph-relevance-v4-blind/benchmark.json `
  --quality-report analytics/datasets/final-gold-v3-20260826/quality_report.json
```

本次 v4 结果：Recall@5 0.5143、MRR 0.5658、NDCG@5 0.4383、Top-1 0.3667、路径来源完整率
1.0，四类泄漏均为 0；Graph MRR 低于文本基线 0.5759。消费回执位于
`outputs/graph-relevance-v4-final/blind_evaluation_receipt.json`，完整报告位于
`analytics/experiments/graph-relevance-v4-blind/benchmark.json`。

该 v4 已揭盲且禁止重复运行。它可以用于下一候选版本的错误分析和回归，但新的放量结论必须
来自另行冻结、模型锁定后才回收标签的全新独立盲测集。v3 即使 12 项全部通过也同样不能授权放量。
