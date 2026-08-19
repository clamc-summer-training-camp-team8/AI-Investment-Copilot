# Agent Interface Draft v0.1

> 状态：团队讨论稿，不是最终接口文档，也不代表已实现。
>
> 标记：✅ 已确认；🟡 建议；❓ 需要和后端/RAG同学确认；🔴 与当前代码冲突。
>
> 本草案已由《Agent Interface Specification v1.0》取代，仅保留讨论过程和设计依据。

## 1. 设计目标与原则

### 1.1 从业务流程推导接口

```text
用户选择 Investment Thesis / Hypothesis
  → Backend 冻结当前业务版本和权限范围
  → 创建 Agent Task
  → Agent 分析当前事件、证据和指标
  → Agent 按需调用 Metric Tool / Evidence Tool / RAG Tool
  → Agent 调用 LLM 并校验结构化输出与 Citation
  → Backend 保存候选结果并创建人工审核任务
  → 研究员确认后，Backend 更新正式状态和版本
```

由此得到的必要接口只有四类：

1. 创建投资逻辑草稿任务。
2. 评估或重新评估一条 Hypothesis。
3. 生成阶段复盘草稿。
4. 查询 Agent Task 状态及结果。

不单独设计“触发 Evidence 更新”接口：新 Evidence 由现有文档上传链路产生，人工修改由 Evidence 管理接口完成；两者都可在必要时触发同一个 Hypothesis Evaluation Task。

### 1.2 边界原则

- ✅ Frontend 只调用 Backend API，不直接调用 Agent、RAG 或 LLM。
- ✅ Backend 拥有业务对象、权限、事务、正式状态和人工门禁。
- ✅ Agent 输入使用版本化 DTO，不接收 ORM 或任意大 JSON。
- ✅ Agent 输出是候选结果，不直接更新 Thesis/Hypothesis。
- ✅ RAG 返回可追溯片段，不返回业务结论。
- 🟡 所有 LLM/RAG 分析统一进入异步 Task，避免 HTTP 请求长期占用。
- 🟡 Agent Service 首先作为进程内逻辑边界，不要求立即拆成独立微服务。

## 2. 接口分层

### 2.1 Backend 对 Frontend：HTTP Task API

负责接收用户操作、鉴权、创建任务和返回可展示状态。

### 2.2 Backend Worker 对 Agent：Agent Service Contract

使用领域 DTO 调用 Agent Workflow。当前可为 Python Protocol/Service；未来独立部署时再映射为 RPC/HTTP，契约本身不变。

### 2.3 Agent 对 RAG/Metric/Evidence：Tool Contract

Agent 只依赖 Tool Port，不依赖数据库、Repository、ORM 或具体 HTTP Client。

## 3. Agent 对外 HTTP 接口

### 3.1 创建投资逻辑草稿任务

| 项目 | 定义 |
|---|---|
| 接口名称 | Create Thesis Draft Task |
| 使用场景 | 研究员基于观点及已有资料生成候选 Thesis/Hypothesis |
| 调用方 | Frontend |
| 被调用方 | Backend |
| Method | `POST` |
| Path | `/api/agent-tasks/thesis-drafts` |
| 是否异步 | 是，返回 `202` |
| task_id | 需要 |
| 幂等 | 需要，`Idempotency-Key` Header |
| 接口响应超时 | 3 秒内完成入队 |
| Agent执行超时 | 建议 120 秒，可配置 |

Request：

```json
{
  "security_id": "688981.SH",
  "view": "国内替代需求和产能利用率修复将推动盈利恢复",
  "as_of": "2026-08-19T10:00:00+08:00",
  "source_document_ids": ["DOC-001"],
  "use_rag": true
}
```

Required Fields：`security_id`、`view`、`as_of`。

Optional Fields：`source_document_ids`、`use_rag`，默认使用 RAG 的具体策略需与后端确认。

Response：

```json
{
  "task_id": "agt_01J...",
  "task_type": "thesis_draft",
  "status": "queued",
  "created_at": "2026-08-19T10:00:01+08:00"
}
```

Errors：

- `400 INVALID_REQUEST`
- `403 FORBIDDEN`
- `404 SECURITY_NOT_FOUND`
- `409 IDEMPOTENCY_CONFLICT`
- `429 TASK_RATE_LIMITED`
- `503 TASK_QUEUE_UNAVAILABLE`

状态：🔴 当前 `/api/theses/drafts` 是同步接口并直接调用 Gateway，未走完整 Agent Runtime。

### 3.2 评估或重新评估单条 Hypothesis

| 项目 | 定义 |
|---|---|
| 接口名称 | Create Hypothesis Evaluation Task |
| 使用场景 | 新证据进入、指标更新、定期检查或研究员主动重新评估 |
| 调用方 | Frontend、Document Worker、Scheduler |
| 被调用方 | Backend |
| Method | `POST` |
| Path | `/api/agent-tasks/hypothesis-evaluations` |
| 是否异步 | 是，返回 `202` |
| task_id | 需要 |
| 幂等 | 需要 |
| 接口响应超时 | 3 秒内完成入队 |
| Agent执行超时 | 建议 120 秒，可配置 |

Request：

```json
{
  "thesis_id": "THS-001",
  "hypothesis_id": "HYP-001",
  "expected_hypothesis_version": 3,
  "trigger": {
    "type": "new_evidence",
    "event_ids": ["EVT-001"],
    "evidence_ids": ["EVD-001"]
  },
  "as_of": "2026-08-19T10:00:00+08:00"
}
```

Required Fields：`thesis_id`、`hypothesis_id`、`expected_hypothesis_version`、`trigger.type`、`as_of`。

Optional Fields：`event_ids`、`evidence_ids`。当 `trigger.type=manual` 时两者可为空。

`trigger.type` 建议枚举：

```text
new_evidence | metric_update | scheduled_review | manual
```

Response 与 3.1 相同，`task_type=hypothesis_evaluation`。

Errors：

- `400 INVALID_REQUEST`
- `403 FORBIDDEN`
- `404 THESIS_NOT_FOUND / HYPOTHESIS_NOT_FOUND`
- `409 OBJECT_VERSION_CONFLICT / IDEMPOTENCY_CONFLICT`
- `422 HYPOTHESIS_NOT_EVALUABLE`
- `429 TASK_RATE_LIMITED`
- `503 TASK_QUEUE_UNAVAILABLE`

状态：🟡 当前 Worker 已能执行类似事件影响分析，但没有统一、可复用的 Hypothesis Evaluation Task API。

### 3.3 创建阶段复盘草稿任务

| 项目 | 定义 |
|---|---|
| 接口名称 | Create Review Draft Task |
| 使用场景 | 到达 `next_review_at` 或研究员主动复盘 |
| 调用方 | Frontend、Scheduler |
| 被调用方 | Backend |
| Method | `POST` |
| Path | `/api/agent-tasks/review-drafts` |
| 是否异步 | 是，返回 `202` |
| task_id | 需要 |
| 幂等 | 需要，建议按 `thesis_id + period + version` |
| 接口响应超时 | 3 秒内完成入队 |
| Agent执行超时 | 建议 180 秒，可配置 |

Request：

```json
{
  "thesis_id": "THS-001",
  "expected_thesis_version": 5,
  "period_start": "2026-04-01",
  "period_end": "2026-06-30",
  "as_of": "2026-08-19T10:00:00+08:00"
}
```

Required Fields：全部字段。

Response 与 3.1 相同，`task_type=review_draft`。

Errors：除通用错误外，包含 `422 INVALID_REVIEW_PERIOD`。

状态：🟡 `ReviewAgent` 已存在；🔴 当前没有正式 API 或 Scheduler 调用。

### 3.4 查询 Agent Task 状态和结果

| 项目 | 定义 |
|---|---|
| 接口名称 | Get Agent Task |
| 使用场景 | 前端轮询、恢复页面、查看失败原因和最终候选结果 |
| 调用方 | Frontend |
| 被调用方 | Backend |
| Method | `GET` |
| Path | `/api/agent-tasks/{task_id}` |
| 是否异步 | 否 |
| task_id | Path中需要 |
| 幂等 | GET天然幂等 |
| 超时 | 建议 5 秒 |

Response（运行中）：

```json
{
  "task_id": "agt_01J...",
  "task_type": "hypothesis_evaluation",
  "status": "retrieving",
  "progress_stage": "retrieving_evidence",
  "created_at": "2026-08-19T10:00:01+08:00",
  "started_at": "2026-08-19T10:00:02+08:00",
  "finished_at": null,
  "result": null,
  "error": null
}
```

Response（完成）：`result` 为 `AgentAnalysisResult`。

状态枚举建议：

```text
queued | retrieving | calculating | generating | validating |
needs_human_review | completed | degraded | failed | cancelled
```

Errors：`403 FORBIDDEN`、`404 TASK_NOT_FOUND`。

状态：🟡 复用一个查询接口承载状态和结果，不再增加无业务价值的 `/result` 接口。

## 4. Backend Worker 对 Agent 的内部契约

```text
AgentService.draft_thesis(request: ThesisDraftAgentRequest)
  → AgentExecution[ThesisDraftCandidate]

AgentService.evaluate_hypothesis(request: AgentAnalysisRequest)
  → AgentExecution[AgentAnalysisResult]

AgentService.draft_review(request: ReviewDraftAgentRequest)
  → AgentExecution[ReviewDraftCandidate]
```

Backend 负责生成 Request 中的权威对象快照。Agent 不根据 ID 自行访问数据库。

## 5. 核心数据结构

所有结构都必须包含 `contract_version`，建议初始为 `agent.v1`；字段变更按兼容性升级。

### 5.1 HypothesisSnapshot

```json
{
  "hypothesis_id": "HYP-001",
  "thesis_id": "THS-001",
  "version": 3,
  "statement": "国内替代需求推动营业收入恢复",
  "hypothesis_type": "经营",
  "importance": "core",
  "status": "validating",
  "observation_window": "每个年度报告期",
  "invalidation_rule": "营业收入同比连续1期低于0%则失效",
  "metric_rules": []
}
```

Required：除 `observation_window`、`invalidation_rule`、`metric_rules` 外均必填。

### 5.2 EvidenceSnapshot

```json
{
  "evidence_id": "EVD-001",
  "event_id": "EVT-001",
  "document_id": "DOC-001",
  "locator": "DOC-001#paragraph-12",
  "fact_excerpt": "2025年营业收入同比增长8.2%",
  "disclosed_at": "2026-03-31T18:00:00+08:00",
  "occurred_on": "2025-12-31",
  "source_type": "annual_report",
  "confirmation_status": "confirmed",
  "existing_direction": "support"
}
```

`existing_direction` 仅用于已判断证据；新证据可以为空。正文不在这里无限扩展，需要时通过 Citation/Evidence Tool 获取。

### 5.3 MetricRuleSnapshot

```json
{
  "metric_id": "revenue_yoy",
  "metric_version": "v1.0",
  "name": "营业收入同比",
  "unit": "%",
  "expected_direction": "not_below_threshold",
  "expected_value": "5.0",
  "invalidation_threshold": "0.0",
  "invalidation_consecutive_periods": 1,
  "observation_window": "annual",
  "expectation_source": "researcher_confirmed"
}
```

Decimal 必须使用字符串传输。Agent 不修改该定义。

### 5.4 MetricObservation

```json
{
  "metric_id": "revenue_yoy",
  "period_end": "2025-12-31",
  "value": "8.2",
  "unit": "%",
  "data_version": "financials-2025a-v1",
  "source_document_id": "DOC-001",
  "citation": {}
}
```

### 5.5 RAGDocumentChunk

```json
{
  "document_id": "DOC-001",
  "chunk_id": "DOC-001#paragraph-12",
  "locator": "DOC-001#paragraph-12",
  "content": "……",
  "published_at": "2026-03-31T18:00:00+08:00",
  "source": {
    "title": "2025年年度报告",
    "source_type": "annual_report",
    "url": "https://example.invalid/report"
  },
  "metadata": {
    "security_id": "688981.SH",
    "industry_id": "semiconductor",
    "visibility": "public",
    "page": 42
  },
  "score": {
    "keyword": 0.71,
    "vector": 0.83,
    "final": 0.78
  },
  "citation": {}
}
```

`metadata` 只允许定义好的白名单字段，不接受任意扩展对象。

### 5.6 Citation

```json
{
  "citation_id": "cit_01J...",
  "document_id": "DOC-001",
  "chunk_id": "DOC-001#paragraph-12",
  "locator": "DOC-001#paragraph-12",
  "page": 42,
  "quote": "2025年营业收入同比增长8.2%",
  "published_at": "2026-03-31T18:00:00+08:00",
  "source_title": "2025年年度报告",
  "source_url": "https://example.invalid/report"
}
```

Required：`citation_id`、`document_id`、`chunk_id`、`locator`、`quote`、`published_at`、`source_title`。

Optional：`page`、`source_url`。

### 5.7 AgentAnalysisRequest

```json
{
  "contract_version": "agent.v1",
  "task_id": "agt_01J...",
  "idempotency_key": "hypothesis:HYP-001:v3:event:EVT-001",
  "as_of": "2026-08-19T10:00:00+08:00",
  "security": {
    "security_id": "688981.SH",
    "name": "中芯国际"
  },
  "thesis": {
    "thesis_id": "THS-001",
    "version": 5,
    "core_view": "国内替代需求和产能利用率修复将支撑盈利恢复"
  },
  "hypothesis": {},
  "trigger": {},
  "current_evidence": [],
  "latest_metric_observations": [],
  "retrieval_scope": {},
  "tool_policy": {}
}
```

Required：

- 契约和任务：`contract_version`、`task_id`、`idempotency_key`、`as_of`。
- 对象：`security`、`thesis`、`hypothesis`、`trigger`。
- 约束：`retrieval_scope`、`tool_policy`。

Optional：`current_evidence`、`latest_metric_observations`，允许空数组。

### 5.8 AgentAnalysisResult

```json
{
  "contract_version": "agent.v1",
  "task_id": "agt_01J...",
  "thesis_id": "THS-001",
  "thesis_version": 5,
  "hypothesis_id": "HYP-001",
  "hypothesis_version": 3,
  "impact_direction": "conflict",
  "hypothesis_assessment": "weakened",
  "confidence": 0.82,
  "reasoning_summary": "收入恢复但毛利率和产能利用率仍低于研究阈值，因此需求假设尚未失效，但盈利传导弱于预期。",
  "supporting_evidence": [],
  "contradicting_evidence": [],
  "metric_assessments": [],
  "citations": [],
  "risk_flags": ["metric_data_incomplete"],
  "open_questions": ["下一季度产能利用率能否持续回升"],
  "requires_human_review": true,
  "generated_at": "2026-08-19T10:00:30+08:00",
  "model_version": "deepseek-chat",
  "prompt_version": "event-impact-v1",
  "retrieval_version": "hybrid-v1"
}
```

枚举建议：

```text
impact_direction:
  support | conflict | neutral | uncertain

hypothesis_assessment:
  holds | weakened | invalidation_candidate | insufficient_evidence
```

说明：

- 不返回模型完整 Chain of Thought，只返回可审计的 `reasoning_summary`。
- `invalidation_candidate` 仍不是正式失效状态。
- `task_status` 位于 Task Envelope，不重复放入业务 Result。
- `confidence` 只用于分流和人工审核，不作为事实概率解释。

## 6. Agent 输入边界

### 6.1 必须直接提供

- 当前任务、时间和幂等信息。
- 目标 Thesis/Hypothesis 的 ID、版本和正式字段。
- 触发事件/证据。
- 指标规则和最新权威观察值。
- 已确认关键证据摘要。
- Backend 计算好的 RetrievalScope 和 Tool Policy。

### 6.2 应通过 Tool 获取

- 更长的原文上下文。
- 历史支持/冲突证据。
- 相似事件。
- 完整指标时间序列。
- 确定性指标计算结果。

### 6.3 不应暴露

- ORM、数据库表名和 Repository。
- 数据库连接和事务。
- 用户Token、密码或完整权限规则。
- 前端页面状态。
- HTTP Session。
- 与当前任务无关的其他用户数据。

## 7. RAG Tool Contract

### 7.1 调用签名

```text
RagTool.retrieve(request: RagRetrieveRequest)
  → RagRetrieveResult
```

### 7.2 Request

```json
{
  "contract_version": "rag.v1",
  "task_id": "agt_01J...",
  "query": "产能利用率下降是否削弱盈利韧性假设",
  "retrieval_scope": {
    "scope_id": "scope_01J...",
    "security_ids": ["688981.SH"],
    "industry_ids": [],
    "visibility_labels": ["public", "team:research-1"],
    "published_from": null,
    "published_to": "2026-08-19T10:00:00+08:00"
  },
  "filters": {
    "document_types": ["annual_report", "announcement", "research_report"],
    "hypothesis_ids": ["HYP-001"],
    "source_types": []
  },
  "top_k": 8,
  "include_content": true
}
```

约束：

- `query` 必填，建议最大 1000 字符。
- `top_k` 建议范围 `1..20`。
- Agent 可以缩小 `filters`，不能修改或扩大 `retrieval_scope`。
- `published_to` 不得晚于 Agent Task 的 `as_of`。
- `retrieval_scope` 建议由 Backend 签发或在服务端按 `scope_id` 回查，最终方式需要确认。

### 7.3 Response

```json
{
  "contract_version": "rag.v1",
  "query_id": "qry_01J...",
  "retrieval_version": "hybrid-v1",
  "embedding_version": "hash-char-2gram-v1",
  "items": [],
  "total_candidates": 126,
  "truncated": false,
  "latency_ms": 84
}
```

`items` 为 `RAGDocumentChunk[]`。

### 7.4 RAG Tool Error

```text
INVALID_QUERY
INVALID_SCOPE
SCOPE_EXPIRED
FORBIDDEN_FILTER
INDEX_NOT_READY
EMBEDDING_UNAVAILABLE
RETRIEVAL_TIMEOUT
RETRIEVAL_UNAVAILABLE
```

建议单次超时 5 秒；Agent Workflow 可降级到 Backend 已提供的基础上下文，但必须在结果中加入 `rag_degraded` 风险标记。

## 8. Metric Tool Contract

```text
MetricTool.get_series(metric_id, security_id, as_of, scope)
  → MetricSeries

MetricTool.calculate(calculation_id, inputs, as_of)
  → MetricCalculationResult
```

计算结果必须包含：

- 公式/计算版本。
- 输入观测值及数据版本。
- Decimal 字符串结果和单位。
- 截止时间。
- 来源 Citation。
- 阈值触发结果。

Agent 解释结果，不重算精确财务指标。

## 9. 标准错误结构

```json
{
  "error": {
    "code": "OBJECT_VERSION_CONFLICT",
    "message": "Hypothesis 已更新，请基于最新版本重新提交",
    "retryable": false,
    "details": {
      "expected_version": 3,
      "actual_version": 4
    },
    "trace_id": "trc_01J..."
  }
}
```

原则：

- Tool/Provider 错误由 Agent 转换为 Agent Task 错误或降级标记。
- Backend 负责将内部错误映射为稳定的 HTTP 错误。
- Frontend 不依赖 Python 异常类名或模型供应商错误文本。

## 10. “重新评估 Hypothesis”完整 Sequence

```text
1. Frontend → Backend（同步）
   POST /api/agent-tasks/hypothesis-evaluations
   Request：hypothesis_id、expected_version、trigger、as_of

2. Backend → DB（同步）
   读取 Thesis/Hypothesis/Metric Mapping/当前已确认证据；校验权限与版本
   Response：权威对象快照

3. Backend → Task Queue（同步）
   创建 Agent Task 和幂等记录
   Response：task_id、queued

4. Backend → Frontend（同步）
   HTTP 202：task_id

5. Worker → Agent Service（异步）
   Request：AgentAnalysisRequest
   Response：AgentExecution

6. Agent → Metric Tool（同步内部调用）
   Request：metric_id、security_id、as_of
   Response：时间序列、计算结果、数据版本和Citation

7. Agent → RAG Tool（同步内部调用，可0..N次）
   Request：query、RetrievalScope、filters、top_k
   Response：RAGDocumentChunk[]、retrieval_version

8. Agent → LLM Provider（同步内部调用）
   Request：Prompt、对象快照、Metric结果、RAG上下文、输出Schema
   Response：结构化候选JSON

9. Agent内部校验（同步）
   Schema、Citation、证据一致性、置信度和人工复核条件
   Response：AgentAnalysisResult 或 degraded/failed

10. Agent → Worker/Backend（异步任务返回）
    Response：候选结果、工具Trace摘要、版本和错误

11. Backend → DB（同步）
    再次校验对象版本，保存候选Evidence/Relation/Task Result，创建ReviewTask

12. Frontend → Backend（同步轮询）
    GET /api/agent-tasks/{task_id}
    Response：needs_human_review + AgentAnalysisResult

13. 研究员确认（后续独立业务接口）
    Backend 更新正式状态、版本和审计；Agent 不参与事务提交
```

## 11. 与当前代码的映射

| 草案能力 | 当前代码 | 状态 |
|---|---|---|
| Thesis Draft | `/api/theses/drafts` + `Gateway.thesis_draft()` | 🔴 同步且绕过完整Runtime |
| Event Impact | Document Worker + `InvestmentResearchAgent.analyze_event()` | ✅ 已有主链，可演进为统一Task |
| Hypothesis Evaluation | 无统一入口 | 🟡 建议在Event Impact上抽象 |
| Review Draft | `ReviewAgent` | 🔴 未接API/Scheduler |
| Task状态 | Document Job和Runtime状态各自存在 | 🟡 需要统一Agent Task Envelope |
| RAG Tool | DB hybrid retrieval + Agent内存Retriever | 🔴 两层契约未统一 |
| Metric Tool | calc规则和Metric数据已存在 | 🟡 尚未形成Agent Tool Contract |
| 人工门禁 | Evidence action/status/version/audit | ✅ 应保持不变 |

## 12. 需要和后端同学确认的10个问题

1. Agent Task 是复用现有 `DocumentProcessingJob/AiRun`，还是建立独立 `AgentTask`？
2. `/api/theses/drafts` 是否允许改为异步；若保持同步，哪类调用必须进入 Runtime？
3. Hypothesis 是否已有独立、稳定且递增的版本号；没有时如何做并发冲突检测？
4. 一个 Event 同时影响多条 Hypothesis 时，是创建一个Task还是每条Hypothesis一个Task？
5. 文档 Worker 触发评估时，幂等键由 `event + thesis + hypothesis + version` 组成是否可接受？
6. Agent 候选结果应保存到现有 Evidence/Relation，还是先保存独立 AnalysisResult 再由人工转入 Evidence？
7. `RetrievalScope` 直接传过滤字段，还是只传由 Backend 签发的 `scope_id/token`？
8. 任务超时、重试次数、取消和人工重跑由哪一层统一管理？
9. ReviewAgent 的触发源是 `next_review_at` Scheduler、用户按钮，还是两者都支持？
10. 前端需要展示多少 Agent Trace：只展示阶段与引用，还是也展示 Tool 查询、检索得分和降级原因？

## 13. 需要和 RAG 同学确认的事项

- `chunk_id` 与当前 `locator` 是否统一为同一稳定标识。
- Metadata 白名单和枚举值。
- 权限过滤由 `scope_id` 还是显式字段驱动。
- `top_k`、单次超时、批量查询和并发限制。
- 是否保证 `published_to <= as_of`。
- 检索版本、Embedding版本和索引版本的返回格式。
- 无结果、部分结果、索引不可用时的标准错误和降级语义。
