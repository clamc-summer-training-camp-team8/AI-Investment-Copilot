# app/workers — 异步任务

主要维护：应用接口方向（问谁，不是评审权限）
PRD 层级：投资逻辑应用层

## 职责

PRD 8.3 列出的两类异步任务，加上定时扫描：

| 任务 | 触发 | 流程 |
| --- | --- | --- |
| 文档处理 | 上传完成 | 解析、切分、实体识别、引用定位，再调 AI 生成卡片草稿 |
| 变化处理 | 新资料入库 | 事件提取、去重、逻辑召回、影响分析，产出候选证据 |
| 复核日扫描 | 定时 | 扫 `next_review_at` 到期与失效条件触发，创建复核任务 |

任务队列用 `arq`（已在 `requirements.txt`）。

启动 worker：

```bash
arq app.workers.settings.WorkerSettings
```

`POST /api/jobs/documents` 将文件保存到受控 `storage/uploads/` 后入队，接口立即返回
`job_id`；同一 `document_id` 使用稳定任务 ID 防止重复入队。模型网络失败按指数间隔最多
重试 3 次，解析失败或达到重试上限后创建高优先级人工复核任务。任务所有者映射保存在
Redis 并带 TTL，查询接口不能跨用户读取结果。

带入库时间的请求必须提交含时区的 `published_at`；触发 AI 草稿时，`thesis_id` 与
`security_id` 必须同时提供。两项都不提供时只执行解析和切分。

## 编排位置

workers 负责**调用顺序与重试**，不负责业务规则。业务规则在 `app/services`。

文档处理链路：

```
ingest.parse → ingest.segment → ingest.fingerprint
  → services.document.persist_processed（原文、段落、正文事实）
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
- 重试次数上限后返回结构化失败结果并创建复核任务；MVP 尚未另建独立死信队列表。
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
