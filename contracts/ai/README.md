# contracts/ai — AI 任务契约

生产方：`app/ai`（`MetricValidation` 由 `app/calc` 生产）
消费方：`app/services`、`web`、`analytics`

对应 PRD 10.1~10.4 的四类 AI 任务与说明书 T11 的数据契约。

## Schema 清单

| 文件 | 契约 | 说明 |
| --- | --- | --- |
| `thesis_draft.schema.json` | 逻辑卡片生成 | 标题、核心观点、2~5 条假设、指标建议、风险、失效条件建议、引用 |
| `event_impact.schema.json` | 批量事件影响分析 | 一条事件对应全部候选假设的逐条相关性、方向、强度、传导路径、建议跟踪项和引用 |
| `metric_validation.schema.json` | 指标验证结果 | 预期差、同比环比、趋势、同业位置、规则结论。由 `app/calc` 产出 |
| `retrospective_draft.schema.json` | 复盘草稿 | 正确判断、错误假设、遗漏风险、领先信号、改进建议、引用 |

## 所有 Schema 的公共必填字段

```json
{
  "model_version":  "调用的模型版本",
  "prompt_version": "提示词模板版本",
  "generated_at":   "生成时间，带时区",
  "ai_status":      "候选 | 低置信 | 解析失败"
}
```

理由：PRD 10.5 要求模型、提示、检索文档和生成时间均版本化；PRD 12.2 要求正式 AI 结论展示来源、引用、模型版本和确认状态。缺任一字段的输出无法满足可追溯性验收（DA-AC-07）。

## 引用字段规则

事实类结论的引用字段必填，格式 `{document_id}#paragraph-{n}`，必须能在 `document_segment` 表中定位到。

无法引用的内容标记为推断或不确定（PRD 10.5 第一条），不允许省略标记直接输出为事实。

## 方向字段用哪个枚举

两个枚举，别混：

- `ImpactDirection`（支持 / 冲突 / 中性 / 无关）：证据或事件**相对具体假设**的影响方向
- `SignalDirection`（正向 / 负向 / 中性 / 不确定）：AI 候选信号方向

字段字典 FLD-007 明确要求区分。两者都不是股价方向，也不是通用情绪极性。

enum 取值必须与 `app/core/enums.py` 完全一致。

## 校验与降级

`app/ai` 的输出先过 Schema 校验：

- 校验失败 → `ai_status = 解析失败`，进人工队列，不抛给用户
- `confidence < low_confidence_cutoff`（默认 0.6）→ `ai_status = 低置信`，进人工队列，**不触发重大风险提醒**（FR-R-007）

## 改动流程

本目录下的改动需 1 个 approve。破坏性变更还需新版本号，并在 PR 里列出要迁移的消费方。改 enum 取值时必须附历史数据映射方案（影响可复算性与前端映射）。

详见 [`../README.md`](../README.md) 的演进规则。
