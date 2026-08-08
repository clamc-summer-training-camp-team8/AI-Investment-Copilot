# contracts/events — 异步任务与内部事件契约

生产方与消费方见下表。

## 清单

| 文件 | 契约 | 生产方 | 消费方 |
| --- | --- | --- | --- |
| `document_ingest.schema.json` | `DocumentIngest` | `app/ingest` | `app/services`、`analytics` |
| `thesis_metric_map.schema.json` | `ThesisMetricMap` | `app/services` | `analytics` |
| `outcome_label.schema.json` | `OutcomeLabel` | `analytics` | `app/services` |
| `evaluation_run.schema.json` | `EvaluationRun` | `analytics` | 人工评审 |
| `task_payload.schema.json` | 队列任务载荷 | `app/api` | `app/workers` |

## 失败处理是契约的一部分

说明书 T11 对每类契约都规定了失败处理，实现时不能自行简化：

| 契约 | 失败处理 |
| --- | --- |
| `DocumentIngest` | 隔离失败文件并记录原因，不删除原文件 |
| `ThesisMetricMap` | 禁止无来源自动生效 |
| `OutcomeLabel` | 截止日未到则保持待观察，不提前生成标签 |
| `EvaluationRun` | 未固化版本不得发布结论 |

## 时间字段（说明书 T9）

事件类载荷必须同时携带四类时间中的相关项：

| 字段 | 含义 |
| --- | --- |
| `occurred_on` | 事实发生时间，无法确认时可为空 |
| `disclosure_time` | 首次公开可得时间，**必填** |
| `ingested_at` | 数据入库时间 |
| `generated_at` | AI 生成时间 |

`disclosure_time` 为空是阻断级错误（DQ-001）。不允许用 `ingested_at` 兜底，那会直接造成未来信息泄露。

`disclosure_time > generated_at` 同样是阻断级错误（DQ-003），`signal` 表有 `CheckConstraint` 兜底。

时间一律带时区。naive datetime 由 `app.core.timeutil` 拒绝。

## 任务幂等

`task_payload` 必须包含幂等键：

- 文档处理用 `content_hash + parser_version`
- 变化处理用事件 `fingerprint`

同一任务重复入队不得产生重复事件（FR-R-005：重复事件合并并保留来源集合，不重复提醒）。

## OutcomeLabel 的窗口约束

DQ-006：窗口标签只能在窗口结束后生成。`label_generated_at >= window_end_on`，`outcome` 表有 `CheckConstraint` 兜底。

窗口起点是首次可得时间的下一可交易时点。当前 `app.core.timeutil.next_observable_day` 只处理日历日，交易日历需接入行情数据源后替换——这对应未关闭的 GAP-003（复权方式、基准和可交易时点待业务确认）。使用这个契约时需知道这个限制。
