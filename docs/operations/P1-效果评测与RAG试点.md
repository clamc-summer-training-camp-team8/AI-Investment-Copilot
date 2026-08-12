# P1 效果评测与 RAG 试点

## 验收结论

P1 已建立可复算效果基线并完成第一轮 pgvector 混合召回试点，但只允许作为候选上下文
小流量启用，不允许自动发布或改变逻辑状态。

独立金标 `mentor-blind-gold-v2-20260811` 共 59 条，覆盖三行业九家公司：

| 任务 | 指标 | 结果 |
| --- | --- | ---: |
| 事件筛选 | Precision / Recall | 96.3% / 86.7% |
| 证券归属 | Accuracy | 100.0% |
| 假设匹配 | Accuracy | 71.2% |
| 方向判断 | 双方相关子集 Accuracy | 30.8% |

方向仍是主要瓶颈，不能把筛选能力解读成完整投研判断能力。金标为单人独立盲标，下一轮需
第二名研究员复标至少 20% 并计算一致性。

## RAG 试点结果

默认 `hash-char-2gram-v1` 是离线可复现的 256 维基线 embedding，不是通用语义模型。
向量按 `index_id + embedding_version` 独立存储，关联 `ingestion_run_id`；新模型不得覆盖旧向量。

59 条独立信息需求的离线结果：

| 方法 | Recall@5 | Recall@10 | MRR |
| --- | ---: | ---: | ---: |
| 关键词长查询基线 | 0.0% | 0.0% | 0.0000 |
| 关键词 + pgvector 混合召回 | 57.6% | 61.0% | 0.4136 |

Top-1 引用正确率为 30.5%。使用仅具备“公开、内部”标签的受限评测身份后，越权结果数为
0。试点通过“无权限泄漏、Recall@5 不差于关键词”门槛，但引用正确率不足以扩大自动化范围。

## 数据流与安全边界

1. 权限标签、证券、行业和披露时间在排序前过滤。
2. `tsvector` 与余弦相似度按配置权重混合，返回 keyword/vector 分项分数和 embedding 版本。
3. 新建逻辑只有研究员显式勾选时使用召回，且只取同证券、当前身份可见切片。
4. “事件→假设”试点由 `RAG_EVENT_PILOT_ENABLED` 显式开启，默认关闭；开启后按事件稳定
   哈希采样（默认 5%），重试不会改变试点分组，并只检索事件披露时点以前、同证券且可见的切片。
5. 召回内容只补充模型候选上下文，命中文档 ID、版本、采样率和数量写审计；模型生成仍是
   候选草稿/候选关联，指标映射、证据确认、发布和状态变更保留人工闸门。
6. RAG 不用于鉴权、去重、确定性计算、失效判定和最终状态变更。

## 流程指标口径

- 当前候选证据 292 条，已复核 0 条，因此全体候选采纳/驳回率均为 0%，已复核子集的
  采纳/驳回率和人工耗时保持 `null`，不能解读成“研究员明确拒绝”。
- 持久化事件 fingerprint 重复提醒为 0/3,790；任务内重复拦截率单列，当前无可统计分母。
- 模型调用当前 5 次可计量、3,630 input tokens、1,174 output tokens；未配置单价，成本为
  `null`。

## 复现命令

```powershell
.\scripts\dev.ps1 up
.\.venv\Scripts\python.exe -m scripts.build_embeddings
.\.venv\Scripts\python.exe -m analytics.evaluation.p1_baseline
.\.venv\Scripts\python.exe -m analytics.evaluation.rag_retrieval_eval
```

结果写入 `analytics/experiments/20260813-p1-evaluation-rag-pilot/`。模型成本只有在审计记录包含
token usage 且配置输入/输出单价时计算；缺失时保持 `null`，不编造成本。
