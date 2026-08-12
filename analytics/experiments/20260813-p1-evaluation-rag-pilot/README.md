# P1 效果基线与 RAG 试点

- 金标：`mentor-blind-gold-v2-20260811`，59 条独立盲标。
- 质量输出：`p1_baseline.json`。
- 召回输出：`rag_retrieval_eval.json`。
- embedding：`hash-char-2gram-v1`，256 维离线确定性基线。
- 权限评测身份：仅“公开、内部”，越权结果 0。
- 结论：混合召回可以进入默认关闭、稳定采样的小流量候选上下文试点，但 Top-1 引用正确率
  30.5%，不得用于自动发布。

复现：

```powershell
python -m analytics.evaluation.p1_baseline
python -m analytics.evaluation.rag_retrieval_eval
```
