# Agent、RAG 与 Backend 职责边界

## 1. 总体原则

```text
Backend：掌握业务状态和流程
RAG：掌握可追溯资料的检索
Agent：掌握研究语义和候选判断
```

Agent 是被 Backend 调用的 AI 服务，并可在单项任务内部执行有限、可审计的 Workflow；它不是全局业务编排器，也不负责正式状态管理。

## 2. 业务对象职责矩阵

| 对象 | 创建 | 更新与确认 | 持久化 | Agent | RAG | Backend |
|---|---|---|---|---|---|---|
| Thesis | 研究员；Agent可给候选草稿 | 研究员确认 | Backend | 生成候选，不直接修改 | 仅使用ID和元数据 | 管理完整生命周期 |
| Hypothesis | 研究员；Agent可拆解候选 | 研究员确认 | Backend | 生成、评估候选 | 可按ID关联资料 | 管理状态和版本 |
| Evidence | 文档链路产生事实；Agent给候选关系 | 研究员确认/驳回 | Backend | 判断支持、冲突或待定 | 检索原文和历史证据 | 管理关系、状态和审计 |
| Metric | 研究员/系统定义；Agent可建议 | 规则服务更新值，人工确认映射 | Backend | 消费计算结果并解释 | 可检索披露原文 | 管理定义、映射和观测值 |

## 3. 模块边界

### Backend 应负责

- HTTP API、身份、权限和事务。
- Thesis/Hypothesis/Evidence/Metric 生命周期。
- 人工门禁、正式状态、版本和审计。
- 异步任务、幂等、重试和调度。
- 构建权威对象快照和 `RetrievalScope`。
- 持久化 Agent 候选结果。

Backend 不应拼接具体 Prompt、实现自然语言判断或依赖具体 LLM 响应格式。

### RAG 应负责

- 文档切片、索引、Embedding 和混合检索。
- 权限、证券、行业和时间过滤。
- 排序、Citation、locator 和检索版本。
- 检索质量评估。

RAG 不判断假设是否成立，不修改业务状态，不承担指标计算。

### Agent 应负责

- 建立候选投资逻辑与可验证假设。
- 理解事件、生成 Query、按需调用受控 Tool。
- 判断证据与假设的支持/冲突/中性/待定关系。
- 输出传导路径、置信度、Citation 和待研究问题。
- Schema、Citation 和一致性校验及有限修复。

Agent 不访问 ORM/数据库，不绕过权限，不直接发布或修改正式状态，不自行完成要求精确性的金融指标计算。

## 4. Agent 的最小输入

Backend 必须直接提供：

- `task_id`、`idempotency_key`、`as_of`。
- Thesis/Hypothesis ID、版本和正式快照。
- 当前新事件/新证据及原文定位。
- 指标定义、阈值、观察窗口和失效规则。
- 当前正式状态及关键已确认证据摘要。
- `RetrievalScope`、允许的 Tool 和调用预算。

Agent 可通过 Tool 获取：

- 历史支持/冲突证据和原文上下文。
- 指标时间序列和确定性计算结果。
- 相似历史事件和相关公司/行业资料。

不应暴露给 Agent：数据库表、ORM 对象、用户凭证、前端页面状态、HTTP Session 和内部事务信息。

## 5. RAG 调用方式

推荐固定召回与动态召回共存：

```text
Backend：固定业务对象版本、权限范围和必要基线材料
Agent：在预算内决定是否需要补充检索及如何构造 Query
RAG：强制执行 RetrievalScope 并返回可追溯片段
```

关键约束：

- Agent 可缩小检索范围，不能扩大权限。
- RAG 必须二次校验权限和 `as_of`。
- 每次 Tool 调用记录 Query、过滤条件、命中结果和索引版本。
- 每个任务限制调用次数、`top_k`、超时和上下文预算。

## 6. 推荐调用结构

```text
Frontend
  → Backend Application
     ├── Auth / Domain Services / Job / Version / Audit
     └── Agent Task Adapter
          → Agent Workflow
             ├── RAG Tool
             ├── Evidence Tool
             ├── Metric Tool
             ├── Schema/Citation Validator
             └── LLM Provider
```

Frontend 只调用 Backend。Agent Service 是逻辑边界，当前不要求独立部署。

## 7. 团队主责

| 能力 | Agent | RAG | Backend | Frontend |
|---|---|---|---|---|
| Thesis/Hypothesis | 生成候选 | 按ID关联资料 | 生命周期主责 | 展示和人工操作 |
| Evidence | 判断候选关系 | 检索原文 | 状态、关系和持久化 | 审核和查看引用 |
| Metric | 建议和解释 | 检索披露资料 | 定义、计算和观测值 | 配置和展示 |
| RAG | 生成动态Query、消费结果 | 索引和检索主责 | 范围控制和固定召回 | 不负责 |
| LLM | 调用和校验主责 | 原则上不负责 | 配置与密钥治理 | 不负责 |
| 权限/状态/版本 | 消费约束 | 执行过滤 | 主责 | 展示授权结果 |
| Task/错误/日志 | 输出运行Trace | 输出检索Trace | 全局串联和产品错误 | 查询和提示 |

## 8. 当前与目标边界的差异

### P0

- Thesis Draft 存在 `API → RAG → Gateway` 与 `Runtime → ThesisDraftAgent` 两条不一致链路，应统一能力入口。
- Worker 以临时字典拼接 Agent 上下文，应定义版本化领域 DTO。
- 数据库 RAG 与 Agent 内存 Retriever 形成双层路径，应建立统一 `RagTool` 契约。
- 必须继续保证 Agent 结果只进入候选状态，人工确认后才能改变正式对象。

### P1

- 建立确定性 Metric Tool。
- 在评估达标后扩大 Event RAG Pilot。
- 接通 ReviewAgent 的定时复盘流程。
- 统一任务状态、错误码和运行审计字段。

### P2

- 依据评估结果引入金融语义 Embedding、Reranker 和多轮检索。
- 建立运行级短期记忆和 Tool Trace 可视化。
- 仅在业务收益明确时引入 Planner 和父子假设级联建议。

