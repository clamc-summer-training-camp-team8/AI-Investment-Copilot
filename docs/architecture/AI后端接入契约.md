# AI Runtime 后端接入契约

## 1. 边界

后端向 `InvestmentResearchAgent` 提供已标准化事件、候选假设和可检索文档。AI Runtime 返回候选结果，不写数据库、不发布 Thesis、不改变正式状态。

正式链路：

```text
数据管道 -> 后端发现新事件 -> 召回候选 Thesis/Hypothesis
        -> AI Runtime -> RuntimeEnvelope -> 后端持久化候选记录
        -> 人工复核 -> 正式 Evidence / Thesis 状态
```

## 2. 真实数据适配

- `real_data/raw/announcements.json` 是公告元数据，当前只有标题和 PDF URL。
- `real_data/dataset/events.csv` 是事件双标注数据，`削弱`在 AI 契约中映射为`冲突`。
- `real_data/dataset/theses.json` 提供 45 个 Thesis 和 135 个候选 Hypothesis。
- 当前公告标题以 `cninfo-title` 作为来源进入检索；获得 PDF 正文后，应由数据管道生成真实段落并替换标题片段。
- 后端不要把前端上传当作主数据源。主路径是数据管道入库后触发事件分析；前端仅展示候选结果和提交人工复核。

## 3. 输入

事件分析调用：

- `AgentEvent`：事件 ID、文档 ID、证券 ID、原文 locator、事件文本、披露时间和事件类型。
- `CandidateHypothesis[]`：后端按证券和已发布状态召回的候选假设。
- `allowed_visibility`：调用者有权使用的资料范围。
- `top_k`：每条假设召回的证据片段数。

没有候选假设时 Runtime 返回 `degraded/no_candidate_hypotheses`，不得记为分析完成。

## 4. 输出 Envelope

后端使用 `app.ai.integration.to_backend_envelope()` 转换，版本为 `ai-runtime-envelope-v1`。主要字段：

- `run_id/task/status/started_at/finished_at`
- `requires_human_review/retryable/degraded_reason/errors`
- `versions.model/prompt/retrieval/schema_name/schema_id`
- `candidate_result`
- `verification.evidence_checks/evidence_grades/consistency_checks`

Envelope 可直接 JSON 序列化，但仍是候选计算结果。后端应另外保存幂等键、任务重试次数、调用人和人工确认记录。

## 5. 状态语义

- `completed`：AI 技术处理完成；仍不代表正式业务确认。
- `needs_human_review`：低置信、证据不足、冲突或模型明确要求复核。
- `degraded`：本次没有可靠完整产出，例如无候选假设、Provider 或 Schema 失败。
- `failed`：非预期程序或配置异常。

`provider_or_schema_failure` 可重试；`no_candidate_hypotheses` 应先补充候选假设，不应盲目重试。

## 6. RAG 接入

`HybridRetriever` 只负责合并全文与向量 Retriever 的排序，并在合并后再次执行证券、时间和权限过滤。向量侧可以由后端后续实现为 pgvector，但必须遵循现有 `Retriever` Protocol。

本支线没有创建 pgvector 表、迁移或任务队列，因为这些属于后端/数据共同边界。接入时不得绕过 `document_id + locator + published_at + visibility_label` 四项约束。
## 7. P1 调用

- `runtime.explain_metric(...)`：后端先调用 `app.calc`，再把固定口径结果传给 AI；不得把原始财务表直接交给模型自行计算。
- `runtime.draft_review(...)`：后端传入选定复盘区间的已有记录；输出恒需人工确认。
- 对应 Schema 为 `metric_explain` 和 `review_draft`，交接仍使用同一个 Runtime Envelope。