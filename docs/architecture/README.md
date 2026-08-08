# 目录架构说明

本文是仓库的架构基线。新增目录、调整依赖方向、改动跨模块契约，都要先改这里，再改代码。

- 分层依赖的机器化约束见 [`layering.md`](layering.md)，由 `make lint-arch` 强制执行。
- 模块所有权与协作流程见 [`../collaboration/README.md`](../collaboration/README.md)。
- 重大取舍记录在 [`../adr/`](../adr/)。

## 1. 架构从业务对象出发

PRD 8.1 明确：架构设计必须围绕卡片对象、业务规则和用户流程展开，不能先于业务定义存在。因此代码结构直接映射 PRD 的六层架构，而不是按技术类型（controller/service/dao）平铺。

| PRD 层级 | 代码位置 | 一句话职责 |
| --- | --- | --- |
| 用户交互层 | `web/`、`app/api`、`app/schemas` | 页面、接口、DTO、权限过滤 |
| 投资逻辑应用层 | `app/workers` | 异步任务、待办、通知的编排 |
| Investment Thesis Engine | `app/services` | 核心对象、关系、状态机、版本、审计 |
| AI 与规则层 | `app/ai`（模型侧）、`app/calc`（规则侧） | 语义理解与确定性计算，严格分开 |
| 数据资源层 | `app/db`、`app/ingest`、`alembic` | 存储、解析、血缘 |
| 外部集成层 | `app/ai/providers`、后续 `app/integrations` | 模型网关与外部系统适配 |
| 离线分析 | `analytics/` | 数据管道、评测、Alpha 实验，不参与线上请求 |

## 2. 为什么把 AI 和计算拆成两个模块

这是整个架构最重要的一条切分。PRD 10.5 与 FR-V-002 要求数值计算由确定性程序完成，模型只解释结果。如果两者混在一个模块里，几乎必然会出现「模型顺手把预期差也算了」的实现，而这类结果无法复算、无法回归测试，直接违反 DA-AC-04。

所以：

- `app/calc` 是纯函数模块，不允许 import `app.ai`、`app.db`、`app.services`。输入是数据类，输出是带口径信息的数据类。可以脱离数据库做单元测试。
- `app/ai` 只负责把文本变成结构化草稿，输出必须过 `contracts/ai/` 的 JSON Schema 校验，低置信度走降级。
- 两者的结果由 `app/services` 汇总，交给人工确认。

`app/calc` 里已有的 `check_invalidation` 说明了这条边界的价值：失效判定必须按逻辑建立日裁剪观察窗口，样例数据中 2025Q2/Q3 连续两期低于预期但都早于建立日 2026-01-15，不裁剪就会在导入数据的瞬间误判失效。这类规则必须是可读、可测、可版本化的代码，不能藏在提示词里。

## 3. 依赖方向

```
web  ─────────────────────────► app/api
                                  │
                    app/workers ──┤
                                  ▼
                            app/services ──────────────┐
                              │      │       │         │
                    ┌─────────┘      │       └───────┐ │
                    ▼                ▼               ▼ ▼
                app/ingest       app/calc        app/ai
                    │                                │
                    └──────────► app/db ◄────────────┘
                                   │
                                   ▼
                                app/core
```

规则：

1. 依赖只能向下，不允许反向或环状。`app/db` 不 import `app/services`，`app/calc` 不 import 任何兄弟模块。
2. `app/core` 是唯一可被所有模块 import 的横切模块，因此只放配置、枚举、时间语义、异常，不放业务逻辑。
3. `app/api` 不直接碰 `app/db`。所有读写经过 `app/services`，否则权限过滤和审计留痕会被绕过（FR-A-003）。
4. `analytics/` 可以 import `app.calc` 和 `app.db`（复用口径与模型），但 `app/` 任何模块都不得 import `analytics`。线上代码不依赖离线代码。
5. 跨模块数据结构一律走 `contracts/`，不允许一个模块直接 import 另一个模块的内部 dataclass。

这些规则由 `.importlinter` 配置并在 CI 中强制执行。

## 4. 目录逐级说明

### 4.1 `app/` 后端单体

MVP 用单体，按模块划分所有权而不是拆微服务。PRD 8.3 已列出「MVP 可与业务服务合并」的组件，过早拆服务会把模块边界问题变成分布式问题。模块边界靠 import-linter 守住，将来要拆服务时按模块切即可。

```
app/
├── core/          配置、枚举、时间语义、异常。全仓可依赖，因此改动最敏感
├── db/
│   ├── models/    ORM：core.py 八类核心对象 + governance.py 版本/审计/质量
│   └── repositories/  仓储层，SQL 只出现在这里
├── ingest/
│   ├── parsers/   PDF / DOCX / TXT 解析
│   └── ...        切片、指纹去重、引用定位
├── calc/          确定性计算 + 状态规则引擎（纯函数）
├── ai/
│   ├── contracts/ 契约校验器（Schema 本体在 contracts/ai/）
│   ├── prompts/   提示词模板，带版本号
│   └── providers/ 模型网关：local 规则实现 / http 私有部署
├── services/      业务编排：thesis / evidence / status / review / version / audit
├── schemas/       API 出入参 Pydantic 模型
├── api/
│   └── routers/   按导航切分：workbench / thesis / radar / review / admin
└── workers/       异步任务：文档处理、变化处理、复核日扫描
```

### 4.2 `analytics/` 离线分析

对应数据分析交付包的四类管道与实验规范。与 `app/` 分开的理由：生命周期不同（实验代码频繁改写、线上代码要求稳定），且 DA-AC-06 要求实验版本固化后才能发布结论，混在一起会让线上发布被实验节奏拖住。

```
analytics/
├── pipelines/     A 资料 / B 指标 / C 标签 / D 评测四类管道
├── datasets/      评测集与金标集版本目录（数据本体不进 git）
├── evaluation/    基线对照、效果指标计算
├── experiments/   候选信号实验，一实验一目录，含经济假设与限制说明
└── notebooks/     探索性分析，不作为交付物
```

### 4.3 `contracts/` 跨模块契约

单一事实来源。任何一处改动都是跨模块事件，需要生产方和消费方共同 approve。

```
contracts/
├── ai/       AI 任务输入输出 JSON Schema（PRD 10.1~10.4 四类任务）
├── api/      OpenAPI 片段与错误码
└── events/   内部事件与异步任务载荷定义
```

### 4.4 `tests/` 测试分层

```
tests/
├── unit/         纯函数，不碰 IO。calc 与 core 的回归测试主要在这里
├── integration/  需要数据库或外部依赖，CI 中带 marker 分开跑
├── contract/     校验 AI 输出与 contracts/ 中 Schema 一致
└── fixtures/     共享夹具，含样例包的最小化派生数据
```

`app/calc` 与 `app/domain` 类规则代码要求单测覆盖阈值边界（达到、接近、未达到、数据缺失四种情形），因为这些分支直接决定是否给研究员发重大风险提醒。

### 4.5 其余目录

- `alembic/` 迁移。每个 PR 最多一个 head，冲突在 PR 内 rebase 解决。
- `web/` 前端。与后端通过 `contracts/api/` 对齐，不读后端内部结构。
- `deploy/` 本地 compose 与试点环境配置。测试与生产隔离（PRD 12.2）。
- `scripts/` 开发脚本，包含样例包导入、契约校验、质量规则执行。
- `docs/` 需求基线（`product/`、`data/`）、架构（`architecture/`）、决策记录（`adr/`）、协作规范（`collaboration/`）。基线文档只读，不在 PR 中随手改。

## 5. 数据流与模块协作

PRD 8.4 的两条主链路对应的模块调用顺序：

**建卡链路**

```
web → api/routers/thesis → services/thesis
  → workers（文档处理）→ ingest（解析、切片、定位）
  → ai（抽取草稿）→ contracts/ai 校验
  → services（保存草稿）→ 人工确认 → services/version（生成 V1）→ db
```

**变化链路**

```
新资料 → workers（变化处理）→ ingest（事件抽取、指纹去重）
  → services（召回候选逻辑与假设）→ ai（影响分析）
  → calc（预期差、趋势、失效判定）
  → services/status（生成状态建议）→ 人工确认 → db + audit
```

两条链路都在「人工确认」处断开：AI 与规则的输出停在候选状态，只有人工动作能推进到正式记录。这是产品定位的技术体现，也是模块边界的划分依据。

## 6. 演进预留

按 PRD 8.5 的阶段划分，以下能力**现在不实现，但目录和接口位置已经确定**，避免将来插不进去：

| 能力 | 阶段 | 预留位置 |
| --- | --- | --- |
| 财务与经营数据接入 | P1 | `app/integrations/market/`，产出写入 `metric_observation` |
| 新闻公告流 | P1 | `app/workers` 新增 source adapter，复用现有事件去重 |
| 组合持仓聚合 | P1 | `app/services/portfolio.py`，只读聚合，不做组合优化 |
| 因子与回测平台 | P2 | `analytics/` 出接口，不自建因子挖掘 |
| 估值/财务模型影响链路 | P2 | `app/calc` 扩展模块，仍由程序计算 |

## 7. 变更本文档的流程

改动分层依赖、模块边界、跨模块契约，需要：

1. 在 `docs/adr/` 提一个 ADR，说明背景、方案、取舍、影响面。
2. 同步更新本文与 `layering.md`。
3. PR 需架构负责人 + 受影响模块负责人 approve。

小改动（补充说明、修正笔误）直接提 PR 即可。
