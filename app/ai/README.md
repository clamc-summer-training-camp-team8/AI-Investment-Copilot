# app/ai — 模型能力与编排

主要维护：AI 能力方向（问谁，不是评审权限）
PRD 层级：AI 与规则层（模型侧）

## 职责

把非结构化文本变成结构化草稿。对应 PRD 10.1~10.4 的四类 AI 任务。

```
ai/
├── agents/      五类业务能力及共享输入输出类型
├── contracts/   契约校验器（Schema 本体在 contracts/ai/）
├── prompts/     提示词模板，带版本号
├── providers/   模型网关：local / mock / http
├── agent.py     旧导入路径的兼容出口
├── retrieval.py 当前 Retriever 接口与关键词/混合检索
├── runtime.py   统一运行状态、能力编排和类型化公共入口
└── integration.py 后端 JSON Envelope
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

## 数据不外发

`llm_provider = local` 时使用规则实现，不外发任何数据。这是默认值。

PRD 12.1：外部模型调用须遵循数据分类和脱敏要求，受限数据使用批准的私有环境。因此：

- 生产配置只允许 `http` 指向私有部署，不接公有云 API。
- 带 `visibility_label = 内部受限` 的文档内容进入提示词前需确认部署环境合规。
- 提示词与请求体不落日志明文。

`local` 提供者的存在还有一个工程价值：其他模块开发时不需要真实模型即可跑通链路，CI 也不依赖外部服务。

## 提示词管理

- 一个任务一个模板文件，文件内声明版本号。
- 提示词改动视为发布行为，需可灰度可回滚（FR-A-002）。
- 提示词变更后需重跑评测集，在 PR 里附对比结果。没有评测对比的提示词改动不合并。

## 边界

- 不 import `app.db`、`app.services`。数据由调用方传入，结果返回给调用方。
- 不写数据库。
- 不做数值计算。
- 不自行改状态。所有输出都是候选，人工闸门在 `app/services`。

## 测试

- `tests/unit/ai/` 用 `local` 提供者，测校验、降级、版本记录。
- `tests/contract/` 断言输出符合 `contracts/ai/` Schema。
- 效果评测不在 `tests/`，在 `analytics/evaluation/`。CI 不跑效果评测，跑的是契约与降级逻辑。

## 公共调用边界

`feat/react-frontend-mvp` 的建卡路由和变化 worker 依赖以下 Gateway 接口，参数保持向后兼容：

- `Gateway.thesis_draft(...)`：生成可由 `services.thesis.create_draft` 保存的草稿；
- `Gateway.event_impact(...)`：生成可由变化 worker 转成候选证据的事件影响；
- `Gateway.metric_explain(...)` 与 `Gateway.review_draft(...)`：提供后续指标解释和复盘能力。

需要 RAG、证据校验和统一运行状态时，调用
`InvestmentResearchAgent.build(gateway, retriever)`，再使用四个显式类型方法：
`draft_thesis`、`analyze_event`、`explain_metric`、`draft_review`。后端在自己的边界把
`ExtractedEvent`、`HypothesisRecord` 和 `Segment` 映射成 `AgentEvent`、
`CandidateHypothesis` 与 `RetrievalDocument`；AI 模块不猜测后端对象字段，也不依赖
FastAPI、ORM、数据库或 `app.services`。

Runtime 返回 `RuntimeExecution`，需要持久化时可用 `to_backend_envelope()` 转成稳定的
`ai-runtime-envelope-v1` JSON 结构。

`feat/mvp-closed-loop-integrated` 额外传入 `thesis_context` 与
`hypothesis_context`，Gateway 和 local/http Provider 均保留这两个显式参数。模型端点
不可用时统一抛出 `app.ai.errors.ModelUnavailable`：可重试错误由 ARQ 重试，配置或
客户端错误进入人工处理；模型已响应但输出不合 Schema 时仍返回 `解析失败`。
