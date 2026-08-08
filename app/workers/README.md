# app/workers — 异步任务

负责人：应用接口负责人
PRD 层级：投资逻辑应用层

## 职责

PRD 8.3 列出的两类异步任务，加上定时扫描：

| 任务 | 触发 | 流程 |
| --- | --- | --- |
| 文档处理 | 上传完成 | 解析、切分、实体识别、引用定位，再调 AI 生成卡片草稿 |
| 变化处理 | 新资料入库 | 事件提取、去重、逻辑召回、影响分析，产出候选证据 |
| 复核日扫描 | 定时 | 扫 `next_review_at` 到期与失效条件触发，创建复核任务 |

任务队列用 `arq`（已在 `requirements.txt`）。

## 编排位置

workers 负责**调用顺序与重试**，不负责业务规则。业务规则在 `app/services`。

文档处理链路：

```
ingest.parse → ingest.segment → ingest.fingerprint
  → ai.extract_thesis_draft → contracts 校验
  → services.thesis.save_draft
```

变化处理链路：

```
ingest.extract_events → ingest.dedupe
  → services.recall_candidates（召回候选逻辑与假设）
  → ai.analyze_impact
  → calc（预期差、趋势、失效判定）
  → services.evidence.create_candidates
  → services.status.record_suggestion
```

两条链路都停在候选状态。**worker 不允许推进到正式记录**，那需要人工动作。

## 性能目标

PRD 12.2：50 页以内资料草稿生成目标 ≤ 3 分钟。

因此文档处理必须异步，上传接口立即返回任务 ID，前端轮询或推送进度。

## 失败与重试（FR-A-004）

要求可查看解析失败、模型失败和任务积压，支持重试和转人工。

约定：

- 任务幂等。同一文档重复处理不产生重复事件（靠 `content_hash` 与 `fingerprint`）。
- 区分可重试失败（模型超时、网络）与不可重试失败（文件损坏、格式不支持）。后者不占重试次数，直接转人工。
- 重试次数上限后进死信队列，写 `data_quality_result`，在管理页可见。
- 失败不静默。任何丢任务的实现都会让研究员上传后无限等待。

## 时间语义

worker 处理时必须区分：

- `published_at` 文档首次公开时间（来自文档）
- `ingested_at` 入库时间（服务器时间）
- `generated_at` AI 生成时间（调模型时刻）

不允许用当前时间填充 `published_at`。这是最容易引入未来信息泄露的地方，DQ-003 是阻断级规则。

## 边界

- 可 import `app.services`、`app.ai`、`app.calc`、`app.ingest`。
- 不 import `app.api`。
- 不直接写业务表。写库经过 `app/services`，否则会绕过审计与版本规则。

## 测试

- `tests/unit/workers/` 用假依赖测编排顺序、重试分类、幂等。
- `tests/integration/workers/` 完整链路。

必须有的测试：同一文档重复入队只产生一份结果；不可重试失败不消耗重试次数；worker 无法把证据推进到"已确认"。
