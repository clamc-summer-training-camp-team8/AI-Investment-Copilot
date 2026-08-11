# AI Agent 与 RAG 实现规格书（MVP）

## 1. 文档目的

本文以《AI Investment Copilot 产品整体架构图（MVP）V1.2》和《AI Investment Copilot 产品需求文档（PRD）V1.2》为基线，定义 AI 编排、RAG 检索和后端交付接口的最小实现范围。

本文不把当前代码视为最终正确实现。现有 `LocalProvider`、规则和 Prompt 作为可替换的 MVP 实现，后续可在不改变业务契约的前提下替换。

## 2. 基线结论
### 2.3 初始投资逻辑与假设的生成边界

本项目的初始投资逻辑和假设允许由 AI 生成。这里的“生成”指生成可供研究员审核的 Thesis Draft，而不是直接形成正式投资结论。

MVP 支持三种输入模式：

1. `view + documents`：研究员提供简短观点，AI 结合公告/研报资料拆解为核心逻辑和候选假设（推荐模式）。
2. `documents only`：研究员只提供资料，AI 从资料中归纳初始观点、2~5 条候选假设及其引用。
3. `view only`：AI 只负责将观点结构化；没有资料支撑的陈述必须标记为待补充证据。

AI 初始输出包括 `title`、`core_view`、2~5 条 `hypotheses`、指标建议、风险、失效条件建议和 citations。AI 不得编造预期值、正式阈值、收益率或交易指令；这些字段在人工审核阶段补充。

因此，正式流程是：

```text
资料/观点 -> RAG 检索 -> AI 生成 Thesis Draft -> 引用与 Schema 校验
        -> 人工修改确认 -> 填写预期值/失效阈值 -> 发布 Thesis V1
```

`Thesis Draft`、`Hypothesis Candidate` 和正式 `Thesis V1` 必须在数据模型和状态上明确区分。AI 可以生成前两者，但不能绕过人工确认直接发布正式版本。

### 2.1 产品主线

```text
研究员观点/资料
  -> Thesis 草稿
  -> Hypothesis 确认
  -> 指标与预期录入
  -> 新资料进入
  -> 事件抽取与 RAG 检索
  -> 事件关联具体假设
  -> 生成候选证据和状态建议
  -> 人工确认
  -> 正式证据、版本和审计记录
```

### 2.2 AI 边界

AI 可以：

- 整理观点和资料，生成 Thesis 草稿；
- 抽取事件、识别候选假设关联；
- 生成支持/冲突/中性/不确定的候选影响判断；
- 生成事实摘要、传导路径和跟踪建议；
- 解释 `app/calc` 已经计算好的结果。

AI 不可以：

- 自动发布 Thesis 或正式状态；
- 自行填写研究员原始预期、正式阈值或失效条件；
- 自行计算预期差、同比、趋势或同业分位；
- 使用未授权或未检索到的事实；
- 输出买卖、评级、目标价或调仓指令。

## 3. MVP 范围

### 3.1 第一条必须跑通的链路

```text
上传/导入公开资料
  -> 解析和切片
  -> 生成可检索段落
  -> 召回已发布 Thesis/Hypothesis
  -> RAG 检索相关证据
  -> Agent 调用 LLM/LocalProvider
  -> JSON Schema 校验
  -> 生成候选 Evidence
  -> 生成 StatusSuggestion
  -> 人工确认
```

### 3.2 第一版 AI 任务

P0：

1. `thesis_draft`：观点和资料 -> Thesis 草稿。
2. `event_impact`：新事件和上下文 -> 假设影响候选。

P1：

3. `metric_explain`：确定性计算结果 -> 面向研究员的解释。
4. `review_draft`：冻结版本和已确认记录 -> 复盘草稿。

第一版不要建设自主多 Agent、自动交易 Agent、复杂因子 Agent 或组合优化 Agent。

## 4. 最小组件设计

### 4.1 一个主 Agent + 工具

运行时只设置一个受约束的业务 Agent：`InvestmentLogicChangeAgent`。

它通过工具完成工作：

| 工具 | 职责 | 是否确定性 |
|---|---|---|
| `recall_theses` | 按证券、权限和状态召回已发布逻辑 | 是 |
| `retrieve_evidence` | 从全文/向量索引召回带 locator 的段落 | 是/检索算法 |
| `analyze_event_impact` | 判断事件与假设的关系和方向 | LLM 或规则 |
| `calculate_metrics` | 预期差、趋势、同业比较等 | 是，调用 `app.calc` |
| `validate_citations` | 检查引用是否来自输入资料 | 是 |
| `create_review_task` | 低置信或冲突结果进入人工队列 | 是 |

Agent 负责编排，不直接写正式业务状态。

### 4.2 Gateway 与 Provider

业务层只依赖 `Gateway`，不直接依赖模型 SDK。

```text
Gateway
  -> LocalProvider       规则实现，离线开发/CI
  -> HttpLLMProvider     机构批准的私有模型接口
  -> MockProvider        测试和演示固定结果
```

Provider 统一实现：

- `model_version`
- `analyze_event_impact(...)`
- `draft_thesis(...)`
- 后续 `explain_metric(...)`、`draft_review(...)`

HTTP Provider 只负责协议适配、超时、重试、响应解析和模型元数据，不负责 Thesis 状态和数据库写入。

### 4.3 Prompt 与模型治理

每次调用必须记录：

- `model_version`
- `prompt_version`
- `retrieval_version`
- `generated_at`
- 输入文档/段落 ID
- 输出 Schema 版本

Prompt 改动必须升级版本，并用冻结评测集重跑对比。

## 5. RAG 规格

### 5.1 RAG 目标

RAG 的目标不是回答通用问题，而是向 Agent 提供“与当前 Thesis 相关、带时间和权限约束、可回到原文”的上下文。

### 5.2 文档标准化字段

```json
{
  "document_id": "doc-001",
  "security_id": "000538.SZ",
  "document_type": "公告",
  "title": "公告标题",
  "source": "cninfo",
  "published_at": "2026-08-01T18:30:00+08:00",
  "occurred_on": null,
  "visibility_label": "公开",
  "content_hash": "sha256...",
  "parser_version": "pdf-parser-v1",
  "segments": [
    {
      "locator": "doc-001#paragraph-12",
      "content": "原文段落",
      "page": 3,
      "ordinal": 12
    }
  ]
}
```

### 5.3 检索流程

```text
候选 Thesis/Hypothesis + 新事件
  -> 权限过滤
  -> security_id 过滤
  -> 时间窗口过滤
  -> 文档类型/主题过滤
  -> 向量或全文召回
  -> Top-K 段落
  -> 去重和上下文拼接
  -> 保留 locator、来源和发布时间
```

第一版可以使用本地 Chroma/FAISS；如果项目统一使用 PostgreSQL，再切换到 pgvector。向量库应通过接口封装，不能让业务层依赖具体数据库。

### 5.4 RAG 输出

```json
{
  "retrieval_version": "retrieval-v1",
  "query": "海外收入是否支持核心业务增长假设",
  "items": [
    {
      "document_id": "doc-001",
      "locator": "doc-001#paragraph-12",
      "content": "原文段落",
      "published_at": "2026-08-01T18:30:00+08:00",
      "score": 0.86,
      "source": "cninfo"
    }
  ]
}
```

RAG 不得扩大来源权限；输入资料没有权限，不能进入检索、Prompt、摘要或引用。

## 6. Agent 输入和输出契约

### 6.1 `event_impact` 输入

```json
{
  "event": {
    "event_id": "event-001",
    "document_id": "doc-001",
    "security_id": "000538.SZ",
    "event_type": "业绩",
    "summary": "事件事实摘要",
    "disclosure_time": "2026-08-01T18:30:00+08:00",
    "evidence_locator": "doc-001#paragraph-12"
  },
  "candidate_theses": [],
  "retrieved_context": [],
  "metric_results": [],
  "as_of_time": "2026-08-11T12:00:00+08:00"
}
```

### 6.2 `event_impact` 输出

```json
{
  "event_id": "event-001",
  "thesis_id": "THESIS-001",
  "hypothesis_id": "THESIS-001-H2",
  "relevance": "相关",
  "impact_direction": "支持",
  "strength": "中",
  "confidence": 0.82,
  "fact": "只能基于输入资料总结的事实",
  "rationale": "影响判断理由",
  "transmission_path": "事件 -> 业务变量 -> 假设",
  "suggested_tracking": ["后续跟踪项"],
  "citations": [
    {"document_id": "doc-001", "locator": "doc-001#paragraph-12"}
  ],
  "ai_status": "候选",
  "requires_human_review": true,
  "model_version": "model-v1",
  "prompt_version": "event-impact-v1",
  "retrieval_version": "retrieval-v1"
}
```

### 6.3 后端接收后的处理

```text
Agent 输出
  -> JSON Schema 校验
  -> 引用存在性校验
  -> 权限校验
  -> 低置信/不确定/冲突进入人工队列
  -> 保存候选 Evidence
  -> 调用 app.calc 生成状态建议
  -> 研究员确认
  -> 正式证据、版本和审计记录
```

Agent 输出不是正式 Evidence，也不是正式 Thesis 状态。

## 7. `data_samples` 适用性评估

### 7.1 已具备的内容

当前 `yunnanbaiyao_20260101_20260811` 样例包含：

- 云南白药单一证券主体 `000538`
- 145 条日线行情
- 10 条新闻，包含新闻正文
- 9 条公告，但主要是标题、日期和详情 URL
- 1 期利润表、现金流量表、资产负债表
- 1 期财务分析指标
- 80 条财务摘要指标
- 3 条券商研报元数据和 PDF 链接
- 东方财富扩展财报字段

### 7.2 作为最小 Demo 输入：基本足够

可以验证：

- CSV 导入和字段标准化
- 单公司实体映射
- 新闻正文切片和 RAG 检索
- 公告元数据接入和事件索引
- 财务指标映射
- 一个 Thesis 的事件影响分析
- 引用、版本和人工确认链路

### 7.3 作为效果验证集：不够

主要缺口：

1. 公告只有标题/URL，没有正文或 PDF 解析文本，无法验证公告 RAG。
2. 财务数据大多只有一个报告期，无法验证趋势、连续期数和预期差序列。
3. 只有一家证券，无法验证同业比较和跨公司泛化。
4. 没有已确认的 Thesis/Hypothesis 及其研究员预期。
5. 没有事件-假设-方向人工金标，无法计算可靠的准确率/召回率。
6. 没有统一 `document_id`、`published_at`、`visibility_label`、`parser_version` 等血缘字段。
7. 新闻和公告的来源时间、事件发生时间、入库时间需要分开。

### 7.4 推荐的最小补充包

```text
1 家公司：云南白药
2 条已确认投资假设
每条假设 2 个指标、1 个预期和 1 个失效条件
10~20 份完整公告/新闻正文
至少 4 个报告期的指标数据
10~20 条人工标注事件
每条事件标注：目标假设、方向、相关性、证据 locator
1 个同业范围和基准口径（可先不做复杂计算）
```

## 8. 验收标准

### 8.1 功能验收

- 能从一份资料生成 Thesis 草稿；
- 草稿包含 2~5 条假设、指标建议、风险和引用；
- 研究员可以修改并发布，AI 不直接发布；
- 新公告/新闻可以召回相关 Thesis/Hypothesis；
- 事件影响输出能定位到输入段落；
- 低置信、解析失败和无权限资料不会进入正式证据链；
- 状态建议由 `app.calc` 和规则生成，正式变化需人工确认；
- 模型不可用时任务保留、可重试，原始输入不丢失。

### 8.2 质量验收

第一轮只做可观测指标，不急于宣称模型能力：

- Schema 通过率；
- 引用存在率和引用支持率；
- Thesis 草稿人工可接受率；
- 事件-假设 Top-3 召回率；
- 影响方向准确率；
- 无关提醒率；
- 人工修改关联率；
- P95 延迟和失败重试率。

所有指标必须记录样本数、数据版本、Prompt 版本、模型版本和人工标注版本。

## 9. 当前必须确认的事项

### 9.1 你需要确认

1. 第一版 Demo 是否确定使用云南白药 `000538`，还是继续使用储能行业案例？
2. 第一条主流程是“Thesis 草稿生成”还是“新资料影响分析”？建议先做后者作为 RAG/Agent 主 Demo。
3. 是否已有可调用的私有 LLM API？接口是否 OpenAI-compatible？
4. 暂无真实 LLM 时，是否接受先用 `LocalProvider/MockProvider` 跑通完整链路？
5. 向量库选 Chroma/FAISS 快速 Demo，还是直接采用 PostgreSQL + pgvector？
6. 公开数据是否允许发送给外部模型？如果不确定，默认只使用 local/mock。
7. 是否允许补抓公告 PDF 和研报 PDF 正文？当前公告 CSV 本身不足以支持 RAG。
8. 第一版是否严格禁止自动状态变更和交易建议？建议保留该限制。

### 9.2 需要和数据同学确认

- 每类文件的真实来源和授权范围；
- 公告/新闻正文获取方式；
- `document_id`、`security_id`、来源和时间字段标准；
- 文档权限标签；
- 事件去重字段和权威来源优先级；
- 指标的单位、币种、报告期和修订版本；
- 至少 4 个报告期的指标样本；
- 10~20 条独立人工标注事件。

### 9.3 需要和产品/业务同学确认

- 首期目标用户和首期行业/公司；
- 2~5 条假设的业务定义和类型；
- “支持/冲突/中性/不确定”的判定标准；
- 哪些字段 AI 可建议、哪些字段必须人工填写；
- 研究员预期值和失效阈值的来源；
- 人工确认人、分歧裁决人和审核流程；
- 状态建议如何触发复核任务；
- Demo 的验收案例和成功标准。

### 9.4 需要和后端/前端同学确认

- Agent 是否同步返回，还是异步任务+轮询；
- API 请求/响应字段和错误码；
- `candidate/low_confidence/parse_failed/confirmed` 状态如何展示；
- 引用点击后如何打开原文并定位段落；
- 模型调用、检索、确认和修改的审计字段；
- 模型不可用、超时和重试的交互；
- RAG 索引重建和版本切换方式。

## 10. 推荐实施顺序

1. 先冻结 AI 输入/输出 Schema 和状态枚举；
2. 用 `MockProvider` 跑通 Agent 编排和 API；
3. 把 `data_samples` 标准化为 document/segment/event/metric 四类输入；
4. 先做全文检索，再接向量检索，保留 locator；
5. 接入真实 LLM Provider，但保留 local/mock 回退；
6. 用 10~20 条人工标注样本做第一轮评测；
7. 接入前端变化卡片和人工确认；
8. 补充多报告期、完整公告正文和第二/第三家公司后，再做效果结论。

## 11. 一句话决策

`data_samples` 足够启动“单公司、单条主流程、可演示”的 Agent/RAG MVP，但不足以支撑跨公司泛化、RAG 质量和 AI 效果结论。实现应先围绕 PRD 的投资逻辑闭环建立稳定契约，再逐步补齐正文、历史期数、人工金标、权限和同业数据。

## 12. 补充后的 Agent 规划

MVP 计划按职责划分为 4 个 Agent 能力（不是 4 个必须同时运行的自主 Agent）：

1. `ThesisDraftAgent`：接收观点和/或资料，调用 Retriever 与 Gateway，生成初始投资逻辑、2~5 条候选假设、指标建议、风险和引用。
2. `InvestmentLogicChangeAgent`：接收新事件和已确认假设，分析支持、冲突、中性或不确定影响，输出候选 Evidence/StatusSuggestion。
3. `EvidenceAgent`：负责引用定位、事实一致性、权限和时间边界校验；低置信度或无依据内容进入人工复核。
4. `ReviewAgent`：汇总 AI 草稿、计算结果和历史版本，生成复盘草稿与待确认事项。

其中 `Gateway/Provider`、`Retriever`、`app.calc` 和 Schema 校验属于共享基础设施，不单独算业务 Agent。MVP 第一阶段只需优先实现前两个 Agent；Evidence 校验可作为编排步骤，ReviewAgent 放在 P1。

推荐执行顺序：

```text
ThesisDraftAgent -> InvestmentLogicChangeAgent -> Evidence 校验 -> ReviewAgent
```

无论 Agent 数量如何增加，正式 Thesis 发布、预期值和失效阈值确认仍由研究员完成。
## 13. Agent 与后端职责边界决策

本支线只实现 `app/ai/` 下的 AI 能力，不直接修改后端路由、业务服务、数据库模型和迁移文件，以降低多人并行开发时的合并冲突。

Agent 采用“一个编排入口 + 可替换能力模块”的组织方式：

```text
后端事件/任务
    -> Agent 编排入口
       -> ThesisDraftAgent
       -> InvestmentLogicChangeAgent
       -> EvidenceAgent
       -> ReviewAgent（P1）
    -> 返回结构化候选结果
    -> 后端负责持久化、状态变更和 API 返回
```

`Gateway`、`Provider`、`Retriever`、Prompt 和 Schema 校验属于 AI 公共基础设施；Agent 不直接写数据库、不发布 Thesis、不改变正式业务状态。后端同学只需依赖 Agent 的输入输出契约，数据格式确定后通过适配层接入。

本次只冻结 Agent 边界，不改变当前 RAG 检索实现和数据库/向量库选型；RAG 存储升级另行评估。
## 14. 从 AI 能力 MVP 到生产级的补充计划

当前 `app/ai` 已完成 Provider/Gateway、关键词检索、基础 Agent 编排、输出 Schema 校验和引用边界检查，但这些属于可测试的 AI 能力层，不等同于完整生产系统。生产化工作应在不改变 Agent 输入输出契约的前提下，由 AI 支线与后端支线协作完成。

### 14.1 生产级目标架构

```text
数据管道/用户请求
        -> 事件队列或任务队列
        -> Agent Runtime
           - 运行状态与步骤记录
           - 超时、重试、幂等和恢复
           - Agent/Skill 路由
        -> Retriever
           - PostgreSQL + pgvector
           - 关键词 + 向量混合检索
           - 证券、时间、权限和来源过滤
        -> Gateway/Provider
           - Local/Mock/HTTP 可替换
           - 模型调用审计与成本记录
        -> Evidence/Output Verification
        -> 后端持久化候选结果
        -> 人工确认
        -> 前端展示正式版本
```

### 14.2 生产化补充项

| 能力 | 当前状态 | 生产化目标 | 负责边界 |
|---|---|---|---|
| Agent 编排 | 多个可独立调用的能力模块 | 统一 Runtime、路由、步骤和状态 | AI + 后端 |
| 运行状态 | 主要记录 AI 输出状态 | `created/retrieving/generating/verifying/needs_human_review/completed/failed/degraded` | 后端持久化，AI 提供状态语义 |
| RAG 存储 | `KeywordRetriever` 内存基线 | PostgreSQL + pgvector，保留 Retriever 接口 | 后端/数据 |
| 检索排序 | 关键词重合度 | 关键词 + 向量混合排序 | AI + 数据 |
| 文档治理 | 基础 locator 和来源字段 | 内容哈希、版本、权限、有效期、软删除、重建索引 | 数据/后端 |
| 模型调用 | Local/Mock/HTTP Provider | 调用日志、延迟、token、成本、失败原因 | AI + 后端 |
| 证据校验 | 引用存在性和越界检查 | 完整性评分、实体匹配、时效性、来源可靠性 | AI |
| 失败处理 | parse_failed/low_confidence | 超时、重试、降级、断点恢复和人工补充 | 后端 + AI |
| 安全控制 | Provider 层基础配置 | API 鉴权、限流、数据权限和敏感信息审计 | 后端 |
| 评测 | 单元测试和少量固定样例 | 金标数据集、离线评测、回归门禁和线上指标 | AI + 数据 |

### 14.3 分阶段实施计划

**阶段 P0：契约和可观测性**

- 冻结 Agent 输入/输出 Schema 和版本字段。
- 为每次运行生成 `run_id`，记录 Agent、Provider、Prompt、Retriever 版本。
- 定义统一状态和错误码，保留原始输入与模型输出。
- 增加支持、冲突、中性、不确定和证据不足的固定评测样例。

**阶段 P1：后端运行时接入**

- 后端通过任务队列触发 Agent，避免 HTTP 请求长时间阻塞。
- 增加超时、有限重试、幂等键和失败恢复。
- 后端保存候选 Evidence/StatusSuggestion，Agent 不直接写正式业务状态。
- 增加运行步骤、模型调用和人工复核记录。

**阶段 P2：RAG 生产化**

- 在现有 PostgreSQL 上启用 pgvector，不额外引入独立向量数据库。
- 文档切片保存 `document_id`、`locator`、来源、发布时间、权限和内容哈希。
- 实现关键词 + 向量混合检索，并保留当前 `Retriever` Protocol。
- 支持文档软删除、有效期过滤和索引重建。

**阶段 P3：证据与模型质量**

- 完善证据完整性评分、实体匹配和时效性检查。
- 增加模型不可用时的规则降级和人工补充路径。
- 建立 Prompt/模型变更的冻结评测和回归门禁。
- 统计 Schema 通过率、引用支持率、人工修改率、Top-K 召回率、P95 延迟和失败重试率。

**阶段 P4：安全和上线保障**

- 增加 API 鉴权、限流、权限隔离和审计日志。
- 对外部模型调用设置数据授权开关，默认禁止未授权资料外发。
- 完成 Docker/数据库迁移/备份/监控和告警配置。
- 以单公司、单主流程 Demo 作为首个验收范围，再扩展到多公司和多行业。

### 14.4 当前支线的验收边界

在后端和数据同学尚未确定最终事件格式前，本支线只验收：

- Agent 模块可独立测试和替换。
- Retriever、Gateway、Provider 契约稳定。
- 输出带有引用、版本和人工复核标记。
- 低置信度、解析失败和证据不足不会被伪装成正式结论。
- 不直接修改后端数据库、队列、API 和正式 Thesis 状态。

生产级能力按上述 P0-P4 分阶段补齐，不能把当前 `KeywordRetriever` 和内存测试结果表述为生产级 RAG。