# Agent Interface Specification v1.0

## 1. 文档控制

| 项目 | 值 |
|---|---|
| 文档名称 | Agent Interface Specification |
| 版本 | 1.0 |
| 状态 | 正式规范 |
| 适用项目 | AI Investment Copilot |
| 适用分支基线 | `phase1_agent` |
| 上游材料 | 《项目现状理解 v1》《Agent、RAG 与 Backend 职责边界》《Agent Interface Draft v0.1》 |

本文使用以下规范词：

- **MUST**：实现必须满足，否则不符合本规范。
- **MUST NOT**：实现禁止执行。
- **SHOULD**：原则上应满足，偏离时必须记录理由。
- **MAY**：可选能力，不影响基础兼容性。

## 2. 目标与范围

本规范定义：

1. Frontend 与 Backend 之间的 Agent Task HTTP API。
2. Backend Worker 与 Agent Service 之间的领域契约。
3. Agent 与 RAG、Metric、Evidence Tool 之间的调用契约。
4. Agent Task 的状态、错误、幂等、超时、版本和审计规则。
5. Agent 候选结果与正式业务状态之间的人工门禁。

本规范不定义：

- 数据库表结构和 ORM 实现。
- 前端页面布局。
- 具体 LLM Provider 的私有参数。
- Prompt 正文。
- Embedding 或 Reranker 的具体模型选型。
- 自动交易、评级或调仓接口。

## 3. 已确认架构决策

### 3.1 模块角色

```text
Backend：业务流程、权限、状态、事务、版本与审计的唯一所有者
Agent：研究语义分析和候选结论的所有者
RAG：受权限和时间约束的资料检索所有者
```

### 3.2 接口决策

1. 所有包含 LLM 或动态 RAG 的生成型任务 MUST 异步执行。
2. Frontend MUST 只调用 Backend，不得直接调用 Agent、RAG 或 LLM。
3. Backend MUST 为每次调用建立 Agent Task，并返回 `task_id`。
4. 一次 Hypothesis Evaluation Task MUST 只评估一条 Hypothesis。
5. 一个 Event 影响多条 Hypothesis 时，Backend MUST 拆分为多条任务，并可用同一 `correlation_id` 关联。
6. Backend MUST 管理任务重试、取消、幂等和结果持久化。
7. Agent MUST 只返回候选结果，不得修改正式 Thesis/Hypothesis 状态。
8. Agent 候选结果通过校验后，Backend MUST 以待人工确认状态物化为 Evidence/EvidenceRelation。
9. RAG MUST 使用 Backend 签发的不可扩大 `scope_id` 执行权限过滤。
10. Review Draft MUST 同时支持 Scheduler 和研究员手动触发。
11. Frontend 默认只展示任务阶段、结果、Citation 和降级原因，不展示模型 Chain of Thought。
12. Agent Service 在 v1.0 中是逻辑服务边界，不要求独立网络部署。

## 4. 总体调用架构

```text
Frontend
  │
  │ HTTP API
  ▼
Backend
├── Authentication / Authorization
├── Thesis / Hypothesis / Evidence / Metric Service
├── Agent Task Service
├── Job / Scheduler
├── Version / Audit
└── Agent Adapter
      │
      │ Agent Service Contract
      ▼
Agent Service
├── Thesis Draft Workflow
├── Hypothesis Evaluation Workflow
├── Review Draft Workflow
├── Context Builder
├── Schema / Citation / Consistency Validator
└── Tool Ports
      ├── RAG Tool
      ├── Metric Tool
      └── Evidence Tool
```

LLM Provider 由 Agent Service 内部调用。Backend 只感知 `model_version`、`prompt_version`、运行状态和标准错误，不感知 Prompt 正文或 Provider 私有响应。

## 5. 通用约定

### 5.1 协议

- HTTP API MUST 使用 HTTPS（本地开发环境除外）。
- Content-Type MUST 为 `application/json`，文件上传接口除外。
- 时间戳 MUST 使用带时区的 ISO 8601。
- 日期 MUST 使用 `YYYY-MM-DD`。
- Decimal MUST 使用字符串传输，不得使用 JSON 浮点数。
- ID MUST 为不透明字符串，调用方不得解析 ID 结构。

### 5.2 版本

- Agent 契约版本：`agent.v1`。
- RAG 契约版本：`rag.v1`。
- Metric 契约版本：`metric.v1`。
- Evidence 契约版本：`evidence.v1`。
- HTTP API MUST 返回 `contract_version`。
- 新增可选字段 MAY 保持同一主版本；删除字段、修改语义或修改枚举 MUST 升级主版本。

### 5.3 鉴权与权限

- Frontend HTTP 请求 MUST 使用 Backend 现有鉴权机制。
- Backend MUST 在创建任务前校验 Thesis/Hypothesis/Document 可见性。
- Agent MUST NOT 接收用户密码、JWT、数据库凭据或完整权限规则。
- Backend MUST 为 Agent Task 创建 `scope_id`。
- Tool MUST 根据 `scope_id` 在服务端重新解析权限，不得信任 Agent 自行提交的可见性标签。

### 5.4 关联标识

每个请求 SHOULD 传播：

| 字段 | 含义 |
|---|---|
| `task_id` | Agent任务唯一标识 |
| `trace_id` | 跨Backend、Agent、Tool和Provider的调用链标识 |
| `correlation_id` | 一组相关任务，如同一Event拆分出的多个Hypothesis任务 |
| `idempotency_key` | 防止重复创建同一业务任务 |

## 6. HTTP API

### 6.1 创建 Investment Thesis 草稿任务

#### 定义

| 项目 | 值 |
|---|---|
| Method | `POST` |
| Path | `/api/agent-tasks/thesis-drafts` |
| 调用方 | Frontend |
| 被调用方 | Backend |
| 成功状态 | `202 Accepted` |
| 是否异步 | 是 |
| 是否需要幂等 | 是 |
| 入队响应超时 | 3秒 |
| 任务默认超时 | 120秒 |

#### Header

```http
Idempotency-Key: thesis-draft:688981.SH:client-request-id
```

`Idempotency-Key` MUST 存在，长度 MUST 为 8..200 字符。

#### Request

```json
{
  "contract_version": "agent.v1",
  "security_id": "688981.SH",
  "view": "国内替代需求和产能利用率修复将推动盈利恢复",
  "as_of": "2026-08-19T10:00:00+08:00",
  "source_document_ids": ["DOC-001"],
  "retrieval_mode": "hybrid"
}
```

| 字段 | 类型 | 必填 | 约束 |
|---|---|---:|---|
| `contract_version` | string | 是 | 固定为 `agent.v1` |
| `security_id` | string | 是 | Backend可识别且当前用户可访问 |
| `view` | string | 是 | 1..2000字符 |
| `as_of` | datetime | 是 | 带时区；检索不得使用其后的资料 |
| `source_document_ids` | string[] | 否 | 最多20个；必须可见且属于允许范围 |
| `retrieval_mode` | enum | 否 | `none`、`fixed`、`hybrid`；默认`hybrid` |

#### Response

```json
{
  "contract_version": "agent.v1",
  "task_id": "agt_01J...",
  "task_type": "thesis_draft",
  "status": "queued",
  "created_at": "2026-08-19T10:00:01+08:00",
  "trace_id": "trc_01J..."
}
```

#### 业务规则

- Agent MUST 生成候选 Thesis/Hypothesis，不得直接发布。
- Backend MUST 将结果保存为草稿或待确认对象。
- `retrieval_mode=none` 时，Agent MUST 只使用 Backend 提供的观点和文档。
- `retrieval_mode=fixed` 时，Backend MUST 预取固定资料，Agent 不得动态调用 RAG。
- `retrieval_mode=hybrid` 时，Agent MAY 在基础资料之外调用 RAG Tool。

### 6.2 创建 Hypothesis Evaluation 任务

#### 定义

| 项目 | 值 |
|---|---|
| Method | `POST` |
| Path | `/api/agent-tasks/hypothesis-evaluations` |
| 调用方 | Frontend、Document Worker、Scheduler |
| 被调用方 | Backend |
| 成功状态 | `202 Accepted` |
| 是否异步 | 是 |
| 是否需要幂等 | 是 |
| 入队响应超时 | 3秒 |
| 任务默认超时 | 120秒 |

#### Request

```json
{
  "contract_version": "agent.v1",
  "thesis_id": "THS-001",
  "hypothesis_id": "HYP-001",
  "expected_thesis_version": 5,
  "expected_hypothesis_revision": "hrev_01J...",
  "trigger": {
    "type": "new_evidence",
    "event_ids": ["EVT-001"],
    "evidence_ids": ["EVD-001"]
  },
  "as_of": "2026-08-19T10:00:00+08:00"
}
```

| 字段 | 类型 | 必填 | 约束 |
|---|---|---:|---|
| `contract_version` | string | 是 | `agent.v1` |
| `thesis_id` | string | 是 | 必须可见 |
| `hypothesis_id` | string | 是 | 必须属于目标Thesis |
| `expected_thesis_version` | integer | 是 | 大于0 |
| `expected_hypothesis_revision` | string | 是 | Backend签发的并发控制令牌 |
| `trigger` | object | 是 | 见下表 |
| `as_of` | datetime | 是 | 带时区 |

Trigger：

| 字段 | 类型 | 必填 | 约束 |
|---|---|---:|---|
| `type` | enum | 是 | `new_evidence`、`metric_update`、`scheduled_review`、`manual` |
| `event_ids` | string[] | 条件必填 | `new_evidence` 时至少提供 `event_ids` 或 `evidence_ids` |
| `evidence_ids` | string[] | 条件必填 | 同上 |
| `metric_observation_ids` | string[] | 条件必填 | `metric_update` 时至少一个 |
| `reason` | string | 条件必填 | `manual` 时1..500字符 |

#### Response

使用统一 `AgentTaskAccepted`，`task_type=hypothesis_evaluation`。

#### 幂等键

Backend MUST 按以下业务信息生成或校验幂等语义：

```text
trigger object + thesis_id + thesis_version + hypothesis_id +
hypothesis_revision + as_of
```

相同幂等键和相同请求 MUST 返回原 `task_id`；相同键但请求体不同 MUST 返回 `409 IDEMPOTENCY_CONFLICT`。

### 6.3 创建 Review Draft 任务

#### 定义

| 项目 | 值 |
|---|---|
| Method | `POST` |
| Path | `/api/agent-tasks/review-drafts` |
| 调用方 | Frontend、Scheduler |
| 被调用方 | Backend |
| 成功状态 | `202 Accepted` |
| 是否异步 | 是 |
| 是否需要幂等 | 是 |
| 入队响应超时 | 3秒 |
| 任务默认超时 | 180秒 |

#### Request

```json
{
  "contract_version": "agent.v1",
  "thesis_id": "THS-001",
  "expected_thesis_version": 5,
  "period_start": "2026-04-01",
  "period_end": "2026-06-30",
  "as_of": "2026-08-19T10:00:00+08:00",
  "trigger_type": "scheduled"
}
```

| 字段 | 类型 | 必填 | 约束 |
|---|---|---:|---|
| `contract_version` | string | 是 | `agent.v1` |
| `thesis_id` | string | 是 | 必须可见 |
| `expected_thesis_version` | integer | 是 | 大于0 |
| `period_start` | date | 是 | 不晚于period_end |
| `period_end` | date | 是 | 不晚于as_of对应日期 |
| `as_of` | datetime | 是 | 带时区 |
| `trigger_type` | enum | 是 | `scheduled`、`manual` |

### 6.4 查询 Agent Task

#### 定义

| 项目 | 值 |
|---|---|
| Method | `GET` |
| Path | `/api/agent-tasks/{task_id}` |
| 调用方 | Frontend、内部监控 |
| 被调用方 | Backend |
| 成功状态 | `200 OK` |
| 是否异步 | 否 |
| 是否需要幂等 | GET天然幂等 |
| 响应超时 | 5秒 |

#### Response

```json
{
  "contract_version": "agent.v1",
  "task_id": "agt_01J...",
  "task_type": "hypothesis_evaluation",
  "status": "needs_human_review",
  "progress_stage": "completed_analysis",
  "progress_percent": 100,
  "created_at": "2026-08-19T10:00:01+08:00",
  "started_at": "2026-08-19T10:00:02+08:00",
  "finished_at": "2026-08-19T10:00:30+08:00",
  "attempt": 1,
  "result": {},
  "error": null,
  "trace_id": "trc_01J..."
}
```

Backend MUST 根据当前用户重新执行任务可见性校验。任务完成前 `result` MUST 为 `null`；失败前 `error` MUST 为 `null`。

### 6.5 不提供的接口

v1.0 不提供：

- 独立 `/agent-tasks/{task_id}/result`：结果由任务查询接口统一返回。
- Agent Evidence Update：Evidence 正式操作沿用 Backend Evidence API。
- Agent Publish Thesis：发布必须使用 Backend 的人工确认接口。
- Frontend 直连 RAG/LLM 接口。

## 7. Agent Task 状态机

```text
queued
  → retrieving
  → calculating（可选）
  → generating
  → validating
  ├── needs_human_review
  ├── completed
  ├── degraded
  └── failed

queued/running → cancelled（仅在尚未提交正式副作用时）
```

| 状态 | 含义 | 是否终态 |
|---|---|---:|
| `queued` | 已创建，等待Worker | 否 |
| `retrieving` | 正在构建上下文或调用RAG/Evidence Tool | 否 |
| `calculating` | 正在调用Metric Tool | 否 |
| `generating` | 正在调用LLM | 否 |
| `validating` | 正在执行Schema、Citation和一致性校验 | 否 |
| `needs_human_review` | 候选结果已保存，等待人工处理 | 是 |
| `completed` | 无需额外人工动作的非状态变更任务完成 | 是 |
| `degraded` | 使用降级路径或结果不完整 | 是 |
| `failed` | 任务失败且本轮不再自动重试 | 是 |
| `cancelled` | 被取消 | 是 |

Hypothesis Evaluation 和 Review Draft 成功后 SHOULD 进入 `needs_human_review`，不得因高置信度自动更新正式状态。

## 8. Agent 内部服务契约

### 8.1 服务接口

```text
draft_thesis(request: ThesisDraftAgentRequest)
  -> AgentExecution<ThesisDraftCandidate>

evaluate_hypothesis(request: AgentAnalysisRequest)
  -> AgentExecution<AgentAnalysisResult>

draft_review(request: ReviewDraftAgentRequest)
  -> AgentExecution<ReviewDraftCandidate>
```

Agent Service MUST NOT 根据对象 ID 直接访问数据库。Backend Adapter MUST 先解析 ID、权限和版本，并传入领域快照。

### 8.2 AgentExecution

```json
{
  "contract_version": "agent.v1",
  "task_id": "agt_01J...",
  "status": "needs_human_review",
  "result": {},
  "error": null,
  "model_calls": [],
  "tool_calls": [],
  "started_at": "2026-08-19T10:00:02+08:00",
  "finished_at": "2026-08-19T10:00:30+08:00"
}
```

`model_calls` 和 `tool_calls` 用于 Backend 审计，不直接完整暴露给普通 Frontend 用户。

## 9. 核心数据契约

### 9.1 ThesisSnapshot

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `thesis_id` | string | 是 | Thesis标识 |
| `version` | integer | 是 | 当前正式版本 |
| `security_id` | string | 是 | 标的 |
| `title` | string | 是 | 标题 |
| `core_view` | string | 是 | 核心观点 |
| `direction` | enum | 是 | `bullish`、`bearish`、`watch` |
| `status` | string | 是 | 当前正式状态 |
| `established_on` | date | 是 | 建立日期 |
| `horizon_end_on` | date/null | 否 | 研究期限 |
| `next_review_at` | datetime/null | 否 | 下次复盘时间 |

### 9.2 HypothesisSnapshot

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `hypothesis_id` | string | 是 | 假设标识 |
| `thesis_id` | string | 是 | 所属Thesis |
| `revision` | string | 是 | 并发控制令牌 |
| `statement` | string | 是 | 假设表述 |
| `hypothesis_type` | string | 是 | 假设类型 |
| `importance` | enum | 是 | `core`、`supporting` |
| `status` | string | 是 | 当前正式状态 |
| `observation_window` | string/null | 否 | 观察窗口 |
| `invalidation_rule` | string/null | 否 | 失效条件 |
| `metric_rules` | MetricRuleSnapshot[] | 是 | 可为空数组 |

Backend MUST 生成稳定的 `revision`。在数据库尚无 Hypothesis 独立版本字段时，MAY 使用正式快照的规范化哈希，但不得使用进程随机哈希。

### 9.3 EvidenceSnapshot

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `evidence_id` | string | 是 | Evidence标识 |
| `event_id` | string/null | 否 | 来源Event |
| `document_id` | string | 是 | 来源文档 |
| `locator` | string | 是 | 稳定原文定位 |
| `fact_excerpt` | string | 是 | 事实摘要，不得包含输入外事实 |
| `disclosed_at` | datetime | 是 | 公开时间 |
| `occurred_on` | date/null | 否 | 事件发生日期 |
| `source_type` | string | 是 | 来源类型 |
| `confirmation_status` | enum | 是 | `pending`、`confirmed`、`rejected` |
| `existing_direction` | enum/null | 否 | `support`、`conflict`、`neutral`、`uncertain` |

### 9.4 MetricRuleSnapshot

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `metric_id` | string | 是 | 指标ID |
| `metric_version` | string | 是 | 指标口径版本 |
| `name` | string | 是 | 指标名 |
| `unit` | string | 是 | 单位 |
| `expected_direction` | enum | 是 | 期望方向 |
| `expected_value` | decimal-string/null | 否 | 预期值 |
| `invalidation_threshold` | decimal-string/null | 否 | 失效阈值 |
| `invalidation_consecutive_periods` | integer/null | 否 | 连续触发期数，1..12 |
| `observation_window` | string/null | 否 | 观察窗口 |
| `expectation_source` | string | 是 | 规则来源 |

### 9.5 MetricObservation

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `observation_id` | string | 是 | 观察值ID |
| `metric_id` | string | 是 | 指标ID |
| `period_end` | date | 是 | 报告期末 |
| `value` | decimal-string | 是 | 数值 |
| `unit` | string | 是 | 单位 |
| `data_version` | string | 是 | 数据版本 |
| `source_document_id` | string | 是 | 来源文档 |
| `citation` | Citation | 是 | 来源引用 |

### 9.6 Citation

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `citation_id` | string | 是 | 引用标识 |
| `document_id` | string | 是 | 文档ID |
| `chunk_id` | string | 是 | 检索切片ID |
| `locator` | string | 是 | 可回查定位 |
| `page` | integer/null | 否 | 页码 |
| `quote` | string | 是 | 支撑结论的最小必要摘录 |
| `published_at` | datetime | 是 | 公开时间 |
| `source_title` | string | 是 | 来源标题 |
| `source_url` | string/null | 否 | 来源链接 |

`citation_id` MUST 由系统生成。Agent 输出的 `quote` MUST 能在对应 `chunk_id` 内容中定位；无法定位时结果 MUST 进入修复或人工审核。

## 10. AgentAnalysisRequest

```json
{
  "contract_version": "agent.v1",
  "task_id": "agt_01J...",
  "trace_id": "trc_01J...",
  "correlation_id": "cor_01J...",
  "idempotency_key": "hypothesis:HYP-001:hrev:EVT-001",
  "as_of": "2026-08-19T10:00:00+08:00",
  "security": {
    "security_id": "688981.SH",
    "name": "中芯国际"
  },
  "thesis": {},
  "hypothesis": {},
  "trigger": {},
  "current_evidence": [],
  "latest_metric_observations": [],
  "retrieval_scope": {
    "scope_id": "scope_01J...",
    "expires_at": "2026-08-19T10:10:00+08:00"
  },
  "tool_policy": {
    "allowed_tools": ["rag", "metric", "evidence"],
    "max_rag_calls": 3,
    "max_metric_calls": 5,
    "max_evidence_calls": 3,
    "max_total_chunks": 20
  }
}
```

### 10.1 必填字段

- `contract_version`
- `task_id`
- `trace_id`
- `idempotency_key`
- `as_of`
- `security`
- `thesis`
- `hypothesis`
- `trigger`
- `retrieval_scope`
- `tool_policy`

### 10.2 可选字段

- `correlation_id`
- `current_evidence`，默认空数组。
- `latest_metric_observations`，默认空数组。

### 10.3 禁止字段

请求 MUST NOT 包含：

- ORM对象、表名或SQL。
- 数据库连接和事务。
- 用户密码、JWT、API Key。
- 前端组件或页面状态。
- LLM Provider HTTP Session。
- 与任务无关的完整资料库内容。

## 11. AgentAnalysisResult

```json
{
  "contract_version": "agent.v1",
  "task_id": "agt_01J...",
  "thesis_id": "THS-001",
  "thesis_version": 5,
  "hypothesis_id": "HYP-001",
  "hypothesis_revision": "hrev_01J...",
  "impact_direction": "conflict",
  "hypothesis_assessment": "weakened",
  "confidence": 0.82,
  "reasoning_summary": "收入恢复但毛利率和产能利用率仍低于阈值，盈利传导弱于预期。",
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

### 11.1 枚举

```text
impact_direction:
  support | conflict | neutral | uncertain

hypothesis_assessment:
  holds | weakened | invalidation_candidate | insufficient_evidence
```

### 11.2 输出规则

- `reasoning_summary` MUST 是面向审计的依据摘要，不得返回模型完整 Chain of Thought。
- `confidence` MUST 在 `[0,1]`，只用于分流，不代表统计概率。
- `supporting_evidence` 和 `contradicting_evidence` MUST 引用输入或 Tool 返回的 Evidence/Citation。
- 每个影响正式判断 MUST 至少有一个有效 Citation；否则 `hypothesis_assessment` MUST 为 `insufficient_evidence` 或任务进入 `degraded`。
- `invalidation_candidate` MUST NOT 被 Backend 自动映射为正式失效。
- `requires_human_review` 对 Hypothesis Evaluation MUST 固定为 `true`。
- Backend 持久化前 MUST 校验 `thesis_version` 和 `hypothesis_revision` 仍为当前版本。

## 12. RAG Tool Contract

### 12.1 接口

```text
retrieve(request: RagRetrieveRequest) -> RagRetrieveResult
```

### 12.2 Request

```json
{
  "contract_version": "rag.v1",
  "task_id": "agt_01J...",
  "trace_id": "trc_01J...",
  "query": "产能利用率下降是否削弱盈利韧性假设",
  "scope_id": "scope_01J...",
  "filters": {
    "security_ids": ["688981.SH"],
    "industry_ids": [],
    "document_types": ["annual_report", "announcement", "research_report"],
    "hypothesis_ids": ["HYP-001"],
    "source_types": [],
    "published_from": null,
    "published_to": "2026-08-19T10:00:00+08:00"
  },
  "top_k": 8,
  "include_content": true
}
```

### 12.3 Request规则

- `query` MUST 为1..1000字符。
- `top_k` MUST 为1..20。
- `scope_id` MUST 由 Backend 签发且未过期。
- Agent MAY 缩小 `filters`，MUST NOT 扩大 `scope_id` 对应权限。
- RAG MUST 将请求过滤条件与服务端 Scope 取交集。
- `published_to` MUST NOT 晚于任务 `as_of`。
- RAG MUST 在排序前执行权限和时间过滤。

### 12.4 RAGDocumentChunk

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

`metadata` MUST 使用约定白名单，不得返回任意内部字段。`chunk_id` 是检索切片标识，`locator` 是可回查原文定位；当前两者可相同，但语义不得合并。

### 12.5 Response

```json
{
  "contract_version": "rag.v1",
  "query_id": "qry_01J...",
  "retrieval_version": "hybrid-v1",
  "embedding_version": "hash-char-2gram-v1",
  "index_version": "segments-20260819-01",
  "items": [],
  "total_candidates": 126,
  "truncated": false,
  "latency_ms": 84
}
```

单次 RAG 调用默认超时为5秒。超时或不可用时，Agent MAY 使用 Backend 基础上下文继续，但 MUST 添加 `rag_degraded` 风险标记。

## 13. Metric Tool Contract

### 13.1 获取指标序列

```text
get_series(request: MetricSeriesRequest) -> MetricSeriesResult
```

Request 必须包含：

- `contract_version=metric.v1`
- `task_id`
- `trace_id`
- `scope_id`
- `security_id`
- `metric_id`
- `metric_version`
- `period_from`
- `period_to`
- `as_of`

Metric Tool MUST 只返回 `as_of` 时点已经公开且有效的数据。

### 13.2 确定性计算

```text
calculate(request: MetricCalculationRequest) -> MetricCalculationResult
```

结果 MUST 包含：

- `calculation_id`
- `formula_version`
- 输入 Observation ID 和数据版本
- Decimal 字符串结果
- 单位
- 截止时间
- Citation
- 阈值触发结果
- 连续触发期数

Agent MUST NOT 用 LLM 重新计算精确金融指标；Agent 只解释 Metric Tool 的确定性结果。

Metric Tool 默认超时为3秒。

## 14. Evidence Tool Contract

### 14.1 获取当前证据

```text
list_evidence(request: EvidenceQueryRequest) -> EvidenceQueryResult
```

Request MUST 包含：

- `contract_version=evidence.v1`
- `task_id`
- `trace_id`
- `scope_id`
- `thesis_id`
- `hypothesis_id`
- `as_of`
- `confirmation_statuses`
- `directions`
- `limit`

Evidence Tool MUST 从 Backend 正式数据读取，不得把未确认候选默认当作已确认事实。

### 14.2 获取引用上下文

```text
get_citation_context(document_id, locator, scope_id)
  -> CitationContext
```

返回 MAY 包含目标片段前后相邻片段，但仍必须执行权限和时间校验。

## 15. 错误契约

### 15.1 标准错误

```json
{
  "error": {
    "code": "OBJECT_VERSION_CONFLICT",
    "message": "Hypothesis 已更新，请基于最新版本重新提交",
    "retryable": false,
    "details": {
      "expected_revision": "hrev_old",
      "actual_revision": "hrev_new"
    },
    "trace_id": "trc_01J..."
  }
}
```

### 15.2 HTTP错误映射

| HTTP | Code | 场景 |
|---:|---|---|
| 400 | `INVALID_REQUEST` | 请求格式或字段不合法 |
| 401 | `UNAUTHENTICATED` | 未认证 |
| 403 | `FORBIDDEN` | 对对象或任务无权限 |
| 404 | `OBJECT_NOT_FOUND` | 业务对象不存在或不可见 |
| 409 | `IDEMPOTENCY_CONFLICT` | 幂等键与请求不一致 |
| 409 | `OBJECT_VERSION_CONFLICT` | Thesis/Hypothesis版本变化 |
| 422 | `OBJECT_NOT_EVALUABLE` | 当前对象状态不允许分析 |
| 422 | `AI_OUTPUT_INVALID` | Schema或Citation修复后仍不可用 |
| 429 | `TASK_RATE_LIMITED` | 超过任务或Provider限额 |
| 503 | `TASK_QUEUE_UNAVAILABLE` | 队列或Worker不可用 |
| 503 | `DEPENDENCY_UNAVAILABLE` | RAG、Metric或LLM不可用 |
| 504 | `TASK_TIMEOUT` | 任务超过总超时 |

### 15.3 重试

- Backend MUST 决定任务级重试，Agent 不得自行创建新任务。
- Provider或Tool的瞬时错误 MAY 重试，默认最多2次。
- 参数错误、权限错误、版本冲突和Schema确定性错误 MUST NOT 自动重试。
- 每次重试 MUST 增加 `attempt`，并保持同一 `task_id` 和 `trace_id`。
- 超过重试次数后任务 MUST 进入 `failed` 或 `degraded`。

## 16. 幂等与并发控制

- Backend MUST 持久化 `Idempotency-Key`、请求规范化哈希和 `task_id`。
- 相同键、相同请求 MUST 返回已存在任务。
- Backend 在保存 Agent 结果前 MUST 再次检查 Thesis/Hypothesis 版本。
- 版本冲突时，结果 MAY 保留为审计记录，但 MUST NOT 物化为当前版本 EvidenceRelation。
- 人工确认接口 MUST 使用独立幂等键和业务版本检查。

## 17. 持久化与人工门禁

### 17.1 Agent Task结果

Backend MUST 保存：

- Request摘要及对象版本。
- AgentAnalysisResult。
- Task状态和错误。
- Model、Prompt、Retrieval、Embedding和Tool版本。
- Citation。
- Tool调用摘要、耗时和降级原因。

### 17.2 候选Evidence物化

当 AgentAnalysisResult 通过 Schema、Citation 和对象版本校验后，Backend MUST：

1. 创建或复用候选 Evidence。
2. 创建状态为待确认的 EvidenceRelation。
3. 生成状态建议，但不得修改正式 Hypothesis/Thesis 状态。
4. 创建 ReviewTask。
5. 写入 AuditLog。

研究员确认、驳回或修改关联后，Backend 才能更新正式关系和对象版本。

## 18. 完整 Sequence：重新评估 Hypothesis

```text
Frontend → Backend（同步）
  POST /api/agent-tasks/hypothesis-evaluations

Backend → DB（同步）
  鉴权；读取Thesis/Hypothesis/Metric Mapping；校验版本

Backend → Agent Task Store / Queue（同步）
  创建task_id、scope_id、idempotency记录并入队

Backend → Frontend（同步）
  202 AgentTaskAccepted

Worker → Backend Domain Services（异步任务内）
  构建权威快照和已确认证据摘要

Worker → Agent Service（同步内部调用）
  AgentAnalysisRequest

Agent → Metric Tool（0..N次同步调用）
  获取时间序列和确定性计算结果

Agent → Evidence Tool（0..N次同步调用）
  获取当前正式证据或Citation上下文

Agent → RAG Tool（0..N次同步调用）
  根据任务生成Query，在scope_id内召回历史资料

Agent → LLM Provider（同步内部调用）
  输入领域快照、Tool结果和输出Schema

Agent内部（同步）
  Schema校验 → Citation校验 → 一致性校验 → 必要时一次修复

Agent → Worker
  AgentExecution<AgentAnalysisResult>

Worker → DB（同步）
  复核对象版本；保存Task结果；物化候选Evidence；创建ReviewTask和Audit

Frontend → Backend（同步轮询）
  GET /api/agent-tasks/{task_id}

Backend → Frontend
  needs_human_review + AgentAnalysisResult

研究员 → Backend（独立业务操作）
  确认/驳回/修改关联；Backend更新正式状态和版本
```

## 19. 可观测性与审计

Backend、Agent 和 Tool MUST 使用同一 `trace_id`。

### 19.1 必须记录

- task类型、状态、attempt和阶段耗时。
- 对象ID及输入版本，不记录无关完整正文。
- Model、Prompt、Schema、Retrieval、Embedding和Formula版本。
- Tool名称、调用次数、耗时、返回数量和错误码。
- Citation ID和Document ID。
- 是否降级、是否需要人工审核。
- 人工最终动作及原因。

### 19.2 禁止记录

- API Key、JWT、密码和数据库凭据。
- 模型完整 Chain of Thought。
- 超出审计需要的用户私有资料全文。

## 20. 当前代码兼容与迁移要求

### 20.1 必须完成的适配

1. 将同步 `/api/theses/drafts` 迁移到统一 Agent Task；过渡期可保留旧接口并返回弃用Header。
2. 将 `InvestmentResearchAgent.analyze_event()` 包装为 `evaluate_hypothesis()` 的内部实现。
3. 统一 Runtime、Document Job 和未来 Agent Task 的状态与错误映射。
4. 定义 `HypothesisSnapshot`、`AgentAnalysisRequest`、`AgentAnalysisResult` 等版本化DTO。
5. 用统一 RagTool Adapter 替代“数据库混合检索后再注入内存Retriever”的双层契约。
6. 建立 `scope_id` 签发和Tool端权限回查机制。
7. 将 `ReviewAgent` 接入 Scheduler 和手动触发Task。
8. 将确定性计算和指标查询封装为 Metric Tool。

### 20.2 必须保持的现有行为

- AI结果始终是候选。
- Evidence必须带来源和可回查locator。
- 正式状态修改必须人工确认并填写原因。
- 所有正式修改必须记录版本和审计。
- Provider不可用和Schema失败必须返回明确降级/错误，不得静默伪装为成功。

## 21. 验收标准

实现符合 v1.0 至少需要满足：

1. 三个创建Task接口均在3秒内返回 `202 + task_id`。
2. 相同幂等键和请求不会重复执行任务。
3. 无权限用户无法创建或读取相关Task。
4. Agent不导入ORM、Repository或数据库连接。
5. RAG Tool无法突破 `scope_id` 的权限和 `as_of` 边界。
6. Hypothesis版本变化后，旧任务结果不能写入当前EvidenceRelation。
7. 每个判断至少有有效Citation，缺失时不得形成确定性结论。
8. Agent不能自动确认Evidence或修改正式Hypothesis状态。
9. Tool/Provider超时产生标准错误或明确降级标记。
10. Task可通过 `trace_id` 串联Backend、Agent、RAG、Metric和Provider日志。
11. Review Draft无论定时还是手动触发，都生成相同契约结果。
12. Frontend无需理解模型Provider和内部异常即可展示任务状态。

## 22. v1.0冻结项

以下内容在 v1.0 中冻结：

- 四个HTTP Task接口及其路径。
- Agent Task状态枚举。
- `AgentAnalysisRequest` 和 `AgentAnalysisResult` 的必填字段。
- `impact_direction` 和 `hypothesis_assessment` 枚举。
- RAG `scope_id` 权限机制。
- Citation最低字段集合。
- Agent只产生候选、人工确认正式状态的边界。
- Decimal字符串和带时区时间约定。

任何破坏上述契约的变更 MUST 进入 `v2` 或经过正式兼容性评审。

