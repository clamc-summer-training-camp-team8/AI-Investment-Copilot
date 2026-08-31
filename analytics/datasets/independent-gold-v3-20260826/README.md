# Independent Gold v3（共识冻结版）

本目录由两份专业复核后的独立标注工作簿通过以下命令生成：

```powershell
.venv\Scripts\python.exe -m analytics.pipelines.gold_annotation_v3 consensus `
  outputs/gold-annotation-v3-20260826/annotator_A_completed_A_20260826.xlsx `
  outputs/gold-annotation-v3-20260826/annotator_B_completed_B-CODEX-FIN-01_20260826.xlsx `
  --output analytics/datasets/independent-gold-v3-20260826
```

三个 `consensus_*` 文件只收录 A/B 核心标签完全一致、双方置信度不低于 3、且双方均标记“无数据问题”的样本。它们可用于离线评测，但不是经过第三方裁决的最终硬金标。

`quality_report.json` 是产品“质量中心”的只读数据源，包含覆盖率、字段一致率、Cohen's kappa、发布门禁与文件哈希。`review/adjudication_queue.csv` 保留 161 个分歧或低置信判断单元，任何最终金标都必须显式处理这些样本，不能静默选择某一位标注者的答案。
