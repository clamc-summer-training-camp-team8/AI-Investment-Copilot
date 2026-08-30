# app/ai — 模型能力与编排

主要维护：AI 能力方向（问谁，不是评审权限）
PRD 层级：AI 与规则层（模型侧）

## 职责

把非结构化文本变成结构化草稿。对应 PRD 10.1~10.4 的四类 AI 任务。

```
ai/
├── agents/      五类业务能力及共享输入输出类型
├── graph_rag.py 可解释的投资知识图与图路径检索
├── skills/      四个模型任务的版本化 SKILL.md
├── contracts/   契约校验器（Schema 本体在 contracts/ai/）
├── prompts/     提示词模板，带版本号
└── providers/   模型网关：local 规则实现 / http 外部或私有兼容端点
```

## 四类任务

| 任务 | 输入 | 输出 | 来源 |
| --- | --- | --- | --- |
| 逻辑卡片生成 | 用户观点、资料正文、投资对象、行业/指标词典 | 标题、核心观点、关键假设、指标建议、风险、失效条件建议、引用 | PRD 10.1 |
| 事件影响分析 | 事件正文与元数据、候选逻辑、候选假设、已有预期和证据 | 相关性、目标假设、方向、强度、事实摘要、传导路径、建议跟踪项、引用 | PRD 10.2 |
| 指标结果解释 | 确定性计算结果 | 结果与假设关系的解释 | PRD 10.3 |
| 复盘草稿 | 冻结的逻辑版本、已确认证据、指标记录、人工动作、最终结果 | 正确判断、错误假设、遗漏风险、领先信号、改进建议、引用 | PRD 10.4 |

注意第三类：**输入是计算结果，不是原始数据**。模型解释预期差为什么发生、对假设意味着什么，但预期差本身由 `app/calc` 算。

## AI 质量规则（PRD 10.5）

四条，逐条对应实现要求：

1. **事实结论必须有引用；无法引用时标记为推断或不确定。** 输出 Schema 中引用字段对事实类结论为必填。
2. **数值计算由程序完成，模型只解释结果及其与假设的关系。** 提示词里禁止要求模型计算关键数值。评审时会查这一点。
3. **模型、提示、检索文档和生成时间均版本化。** 每次调用记录 `model_version`、`prompt_version`、`generated_at`，写入 `signal` / `evidence`。
4. **评测集覆盖不同文档类型、正反证据、口径冲突、歧义实体和历史时点。** 评测在 `analytics/evaluation/`。

## 输出必须过 Schema 校验

所有模型输出先过 `contracts/ai/` 的 JSON Schema，再进业务流程。校验失败按 `ai_status = 解析失败` 处理，进人工队列，不抛给用户。

契约变更规则见 [ADR-0004](../../docs/adr/0004-契约优先的跨模块协作.md)。改 `contracts/ai/` 下的 Schema 需 1 个 approve，本模块内部实现的改动 CI 绿即可自合。

## 降级规则

FR-R-007：低置信结果进入人工队列，不升级提醒。

`RuleThresholds.low_confidence_cutoff`（默认 0.6）以下的输出：

- `ai_status` 标 `低置信`
- 进人工队列
- **不触发重大风险提醒**

降级规则必须可测试（FR-R-007 验收要点）。阈值在 `app/core/config.py`，不硬编码。

## 模型数据与密钥

`llm_provider = local` 时使用规则实现，不外发任何数据。这是默认值。

`http` 可指向公有云或私有兼容端点。API Key 只从服务端环境变量或密钥管理系统读取，
不得写入仓库、返回前端或出现在日志中；提示词与请求体同样不落日志明文。

`local` 提供者的存在还有一个工程价值：其他模块开发时不需要真实模型即可跑通链路，CI 也不依赖外部服务。

`llm_provider = http` 已实现 OpenAI-compatible `chat/completions` 适配器。DeepSeek
推荐配置为 `https://api.deepseek.com/chat/completions` + `deepseek-v4-flash`。配置
`LLM_ENDPOINT`、`LLM_MODEL_VERSION` 和由密钥管理系统注入的 `LLM_API_KEY` 后启用。
适配器固定结构化 JSON 输出、超时和有限重试，并由 Gateway 追加模型/提示词版本后再过
`contracts/ai/` 校验。远程端点必须使用 HTTPS（只有 localhost/回环地址可用 HTTP）。
HTTP 4xx 视为不可重试配置错误；408、429、5xx 和网络错误可重试。

## 提示词管理

- 一个任务一个模板文件，文件内声明版本号。
- 提示词改动视为发布行为，需可灰度可回滚（FR-A-002）。
- 提示词变更后需重跑评测集，在 PR 里附对比结果。没有评测对比的提示词改动不合并。

## 边界

- 不 import `app.db`、`app.services`。数据由调用方传入，结果返回给调用方。
- 不写数据库。
- 不做数值计算。
- 不自行改状态。所有输出都是候选，人工闸门在 `app/services`。

Graph RAG 同样遵守该边界：图是关系库正式对象按来源、观测、语义、研究和摘要层形成的只读
投影，默认只沿已确认边进行单向跨层遍历；它只返回带原文 locator 的候选上下文、图快照和
路径解释，不创建或确认任何业务关系。实现与验收口径见
[`../../docs/architecture/Graph-RAG实现说明.md`](../../docs/architecture/Graph-RAG实现说明.md)。

默认发布策略使用 `graph-evidence-fusion-v1`：在候选池、证券、权限和时间边界内确定性融合文本、
中文 BM25 与 Graph 路径排序，并保留路径、图分、快照和分支排名。v6 专业研究员一次性盲测已
14/14 通过，因此 `RAG_GRAPH_ENABLED` 默认开启、`RAG_GRAPH_ASSIST_ONLY` 默认关闭；需要保序
兼容时仍可显式启用 assist 模式，运行时异常继续回退到文本检索。

## 测试

- `tests/unit/ai/` 用 `local` 提供者，测校验、降级、版本记录。
- `tests/contract/` 断言输出符合 `contracts/ai/` Schema。
- 效果评测不在 `tests/`，在 `analytics/evaluation/`。CI 不跑效果评测，跑的是契约与降级逻辑。
- `tests/unit/ai/test_http_provider.py` 使用 HTTPX MockTransport 验证鉴权头、结构化输出、
  瞬时失败重试和不可重试错误，不调用真实模型、不消耗额度。
