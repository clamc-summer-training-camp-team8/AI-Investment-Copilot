# contracts — 跨模块契约

主要维护：架构与工程方向
评审：本目录下的改动需 1 个 approve（改动的代价由消费方承担，消费方要有话语权）
决策背景：[ADR-0004](../docs/adr/0004-契约优先的跨模块协作.md)

## 定位

跨模块接口的**单一事实来源**。模块之间不通过读对方源码对齐，通过读这里的契约文件对齐。这样生产方和消费方可以并行开发。

```
contracts/
├── ai/       AI 任务输入输出 JSON Schema
├── api/      OpenAPI 片段与统一错误码
└── events/   异步任务载荷与内部事件定义
```

## 契约清单

来自数据分析说明书 T11 的六类数据契约与 PRD 10.1~10.4 的四类 AI 任务：

| 契约 | 生产方 | 消费方 | 位置 |
| --- | --- | --- | --- |
| `DocumentIngest` | `app/ingest` | `app/services`、`analytics` | `events/` |
| `ThesisDraft` | `app/ai` | `app/services` | `ai/` |
| `EventImpact` | `app/ai` | `app/services` | `ai/` |
| `MetricValidation` | `app/calc` | `app/services`、`app/ai` | `ai/` |
| `RetrospectiveDraft` | `app/ai` | `app/services` | `ai/` |
| `ThesisMetricMap` | `app/services` | `analytics` | `events/` |
| `OutcomeLabel` | `analytics` | `app/services` | `events/` |
| `EvaluationRun` | `analytics` | 人工评审 | `events/` |
| HTTP 接口 | `app/api` | `web` | `api/` |

每类契约的失败处理也是契约的一部分：

| 契约 | 失败处理 |
| --- | --- |
| `DocumentIngest` | 隔离失败文件并记录原因 |
| `ThesisMetricMap` | 禁止无来源自动生效 |
| `EventImpact` | 低置信度进入待复核 |
| `MetricValidation` | 缺失时输出信息不足 |
| `OutcomeLabel` | 截止日未到则保持待观察 |
| `EvaluationRun` | 未固化版本不得发布结论 |

## 演进规则

**兼容变更**（可直接提 PR）：新增可选字段、补充描述、放宽格式限制。

**破坏性变更**（需新版本号）：删除字段、改字段类型、改必填性、改枚举取值、收紧格式限制。

破坏性变更流程：

1. 新增版本号（Schema 内 `version` 字段 + 文件名或目录带版本）。
2. 旧版本保留，直到所有消费方迁移完成。
3. 在 PR 里列出需要迁移的消费方与预期完成时间。
4. 迁移完成后单独提 PR 删除旧版本。

## 枚举取值特别注意

Schema 里的 enum 必须与 `app/core/enums.py` 一致。改枚举取值同时影响：

- 历史数据可复算性（旧数据存的是旧取值）
- JSON Schema 校验（旧输出会校验失败）
- 前端展示映射

因此改枚举取值必须在 PR 里给出历史数据的映射方案。评审的重点就是看这个方案，不是看格式。

## 评审要求

`contracts/` 下的改动需 **1 个 approve**，由 `.github/CODEOWNERS` 保证。这是全仓仅有的四类强制评审路径之一（其余改动 CI 绿即可自合）。

这里刻意保留摩擦：契约改动的代价由消费方承担，所以消费方要有话语权。破坏性变更时在 PR 里 @ 上受影响的消费方，别让对方在接口挂掉时才发现。

## 契约测试

`tests/contract/` 校验实现输出与契约一致，CI 必跑。

新增契约时同时新增契约测试。只有 Schema 文件没有测试，等于契约随时可能与实现漂移。

## 与 app/schemas 的区别

| | `contracts/` | `app/schemas/` |
| --- | --- | --- |
| 形式 | JSON Schema / OpenAPI，语言无关 | Pydantic 模型，Python |
| 用途 | 跨语言、跨在线离线边界的约定 | Python 侧的实现与校验 |
| 谁是权威 | 是 | 不是，以契约为准 |

若某类契约长期只有一个后端生产方和一个后端消费方，可以退化为共享 Pydantic 模型放 `app/schemas`。跨前后端、跨在线离线的边界不适用这个退化。
