# Phase 2 集成分支合并记录

> 日期：2026-08-30
>
> 集成分支：`phase2-integrated`
>
> 集成提交：`60a30988398670122b4c5666ae1fcdeef42f4a93`
>
> 状态：已完成合并、验收并推送远端

## 1. 合并目的

本次工作把三名成员并行维护的 Phase 2 成果汇总到一个可继续协作开发的远端分支：

| 远端分支 | 合并时 HEAD | 主要职责 |
| --- | --- | --- |
| `phase2-graph-rag-p0` | `5256fa350cb9af3b0d21e8ae4847626aeb03f780` | Graph RAG P0、v4-v6 独立盲标、图文融合、默认启用决策 |
| `phase1_agent` | `be4e4e906fd8a6b94acf87be67f987e916508dbc` | Agent Runtime、多事件多假设批量契约、指标与复核工作流 |
| `feature/full-product-snapshot-20260830` | `1c7bf335fef459e50fed39264953d0520cc7aed5` | 完整产品快照、排序先验 RAG、主题排序、前端页面与汇报资产 |

说明：任务描述中的 `phase1-agent` 在远端仓库的实际名称是 `phase1_agent`，本次按实际远端分支完成合并。

三个分支的共同基线为 `c1aef4f`（`phase1-integrated`）。从共同基线计算，Graph RAG、Agent、完整产品快照分支分别包含 4、7、2 个提交。

## 2. 集成策略与提交拓扑

为避免覆盖任何成员分支，本次从 `phase2-graph-rag-p0` 创建新分支 `phase2-integrated`，再按依赖关系依次合并 Agent 与完整产品快照：

```text
c1aef4f  phase1-integrated
├── 2db0858 ... 5256fa3  phase2-graph-rag-p0
│                    \
│                     6795f44  合并 phase1_agent
│                    /       \
├── 92571cd ... be4e4e9       60a3098  合并完整产品快照
│                            /
└── c5331e5 ─────── 1c7bf33  feature/full-product-snapshot-20260830
```

产生的两个合并提交为：

1. `6795f44940c85133a9e1e8eeca27251f6d07a671`

   `merge: integrate phase1 agent into phase2`

2. `60a30988398670122b4c5666ae1fcdeef42f4a93`

   `merge: integrate full product snapshot into phase2`

合并完成后通过 `git merge-base --is-ancestor` 验证，三个源分支的 HEAD 均为 `phase2-integrated` 的祖先。三个源分支没有被 force push、reset 或改写。

## 3. 各分支能力在集成版本中的落点

### 3.1 Graph RAG

Graph RAG 分支作为集成起点，其能力完整保留：

- 公司逻辑、假设、事件、证据、指标与文档片段构成图语料；
- 图召回与文本召回通过 Evidence Fusion 共同参与候选排序；
- `seed_node_ids` 从目标假设出发约束图扩展；
- 证据保存 `score_components`、`graph_paths`、`graph_snapshot` 等可追踪信息；
- worker 返回 `retrieval_mode`、召回排名与 `graph_snapshot_id`；
- v4-v6 盲标、金标、评测报告和研究员交付物继续纳入版本控制；
- Graph RAG 默认开启：`RAG_GRAPH_ENABLED=true`；
- 已从辅助模式切换为正式融合：`RAG_GRAPH_ASSIST_ONLY=false`。

### 3.2 Agent Runtime

Agent 分支的批量运行与治理能力完整并入变化链：

- 一份资料的多个事件与一条公司逻辑下的多个假设可批量分析；
- 使用 `AgentEventInput`、`HypothesisInput` 与 `AgentRunResult` 统一契约；
- 保留候选生成、证据校验、低置信降级、人工复核与运行审计；
- 文档处理任务继续通过事务化 `uow_scope()` 写入进度和结果；
- 指标推荐、指标解释、逻辑修订草稿与复核草稿工作流继续可用；
- 已有人工标注或上游确认目标假设时，批量模型返回的其他假设结果不会扩散为额外候选证据。

### 3.3 排序先验 RAG 与完整产品快照

完整产品快照分支提供的能力也完整保留：

- 排序先验快照、先验条目、排序 Profile 与可解释得分；
- 逻辑主题归一化、主题关系与主题排序；
- 排序检索 API、数据仓储、评测脚本与九家公司数据资产；
- 覆盖总览、宏观策略、更新详情、复盘中心和吉利公司页等完整产品页面；
- 中期答辩 PPT、页面截图和演示资料。

## 4. 核心冲突与裁决

### 4.1 Graph RAG 与 Agent 的第一次合并

第一次合并涉及下列冲突文件：

```text
app/ai/README.md
app/ai/agents/logic_change.py
app/core/domain.py
app/db/repositories/evidence.py
app/workers/change_chain.py
app/workers/jobs.py
contracts/api/openapi.yaml
docs/architecture/AI-Agent-RAG实现进度.md
tests/unit/workers/test_upload_change_chain.py
web/src/App.tsx
web/src/api.ts
web/src/mocks.ts
web/src/pages.tsx
```

裁决原则不是简单选择某一侧，而是按产品规则合成：

| 冲突面 | 最终裁决 |
| --- | --- |
| 投资逻辑模型 | 保持“一个公司只维护一条当前投资逻辑”，一条逻辑下允许多个互补假设 |
| Agent 调用 | 使用 Agent 分支的新批量契约，不退回旧的逐事件单假设接口 |
| Graph RAG | 把图检索器、假设种子节点、图路径与融合得分重新接入新 Agent 批量链路 |
| 证据数据结构 | 同时保留 `retrieval_trace` 和 `ingested_at` |
| worker 结果 | 同时返回 Agent 任务详情与 Graph RAG 的模式、快照和召回排名 |
| API 契约 | 合并两侧新增 Schema 与路径，最终 OpenAPI 保持单一有效文档 |
| 前端 | 保留 Agent 工作台、Graph 质量页与量化页，不删减任一已交付能力 |
| 测试口径 | 将旧的“同公司多条投资逻辑”用例改为“一条公司逻辑、多条假设” |

### 4.2 完整产品快照的第二次合并

第二次合并只产生两个文本冲突：

```text
web/src/App.tsx
web/src/pages.tsx
```

最终没有用静态产品快照覆盖可操作页面，而是让两类页面并存：

- `/workbench`：完整产品快照工作台；
- `/operations`：API 驱动的任务与操作工作台；
- `/reviews`：API 驱动的 Agent/Graph 治理入口；
- `/retrospective`：完整产品快照复盘中心；
- `/coverage`、`/macro-strategy`、`/updates`、`/companies/geely`：完整产品展示页；
- `/radar`、`/theses`、`/assets`、`/quality`、`/quant`：原有业务和质量页面。

这样既保留了完整产品表达，也没有牺牲真实接口联调与研究员操作链路。

## 5. 合并后发现并修复的兼容问题

分支可以分别通过测试，不代表组合后仍满足全仓约束。本次在合并阶段额外处理了以下问题。

### 5.1 线上与离线模块边界

Agent 工作流曾直接导入 `analytics.pipelines.fetch_financials`，同时 `app.ai` 中的经营指标工具直接依赖 `app.ingest`。这会破坏仓库分层约束。

最终处理：

- 在线请求只读取已审核的财务快照，不在请求链路直接执行离线采集管道；
- 财务快照刷新继续由 `analytics/` 离线任务负责；
- `company_metrics.py` 从 `app.ai.tools` 移到 `app.services`，由服务层协调采集与 AI；
- Import Linter 的 6 条架构契约全部恢复通过，没有通过放宽规则规避问题。

### 5.2 检索结果 DTO 向后兼容

Graph RAG 为 `AssetSearchHitRecord` 增加了 `published_at` 和 `source`，而排序 RAG 的部分调用仍使用原有位置参数。若直接把新字段插在中间，会导致旧参数被错误映射。

最终把新增元数据调整为可选的尾部字段，并要求需要时间与来源的 Agent 路径过滤缺少发布时间的旧结果，兼顾旧调用兼容与未来信息防泄漏要求。

### 5.3 批量 Agent 与人工金标

新 Agent 契约要求模型对全部候选假设逐项返回结果。本地确定性模型会因此为一个已标注事件生成多条候选证据。

最终规则是：批量输出仍保持完整，以满足契约和审计；但事件已经携带人工确认的 `hypothesis_id` 时，仅目标假设可以进入正式候选证据链。人工金标优先级高于模型扩展结果。

### 5.4 可复算案例与时间漂移

真实案例和 MVP 闭环测试原先会读取开发者本地 `.env`，可能意外调用 HTTP 模型；同时直接使用运行当天判断历史指标新鲜度，导致案例随日期推移变红。

最终把回归案例固定为本地确定性模型，并使用案例对应的历史 `as_of` 日期。线上服务仍按真实当前时间判断数据是否过期，测试则保持可复算。

### 5.5 数据库集成测试隔离

pgvector 测试原先假设开发数据库中没有其他公开检索结果，并断言所有命中项来源名称相同。恢复真实数据库后，该假设不成立。

最终改为只校验本测试插入的目标文档来源，同时继续校验权限标签、发布时间、embedding 版本以及机密文档不泄漏。

## 6. Alembic 多迁移头处理

三个并行分支都从 `0011_ai_runtime_observability` 创建了自己的迁移链：

```text
0011_ai_runtime_observability
├── 0012_evidence_retrieval_trace
│   └── 0013_one_thesis_per_security
├── 0012_thesis_kind
│   └── 0013_seed_agent_metrics
└── 0012_ranking_prior_rag
    └── 0013_logic_topic_ranking
```

直接合并代码会产生三个 Alembic head。为保证所有环境能够执行完整迁移，新增汇合迁移：

```text
0013_one_thesis_per_security ─┐
0013_seed_agent_metrics ──────┼── 0014_phase2_integrated_heads
0013_logic_topic_ranking ─────┘
```

`0014_phase2_integrated_heads` 本身不改变数据，只声明三条链的共同后继。实际在本地 PostgreSQL 上从 Graph 分支的 `0013_one_thesis_per_security` 升级后，Agent 与排序 RAG 两条缺失链均成功执行，最终只剩一个 head。

## 7. 验收结果

### 7.1 后端与契约

| 检查项 | 结果 |
| --- | --- |
| Pytest 全量测试 | `472 passed, 1 skipped` |
| Ruff 静态检查 | 通过 |
| Ruff 格式检查 | 318 个文件通过 |
| Mypy | 149 个源文件通过 |
| Import Linter | 6 条契约通过，0 条破坏 |
| OpenAPI | 3.1.0 解析成功，共 62 条路径 |
| Alembic | 唯一 head：`0014_phase2_integrated_heads` |

唯一跳过项是仓库原有的条件性场景，不是本次合并新增失败项。

### 7.2 前端

| 工程 | 检查项 | 结果 |
| --- | --- | --- |
| `web/` | ESLint | 通过 |
| `web/` | TypeScript + Vite production build | 94 个模块构建成功 |
| `web_demo/` | ESLint | 通过 |
| `web_demo/` | TypeScript + Vite production build | 91 个模块构建成功 |

### 7.3 运行依赖

本地验收时以下服务均处于 healthy 状态：

- PostgreSQL + pgvector；
- Redis；
- MinIO。

### 7.4 Git 与远端

- `phase2-integrated` 已推送到 `origin/phase2-integrated`；
- 本地与远端 ahead/behind 为 `0/0`；
- 三个源分支 HEAD 均未改变；
- Graph RAG 分支中已跟踪的 `outputs/` 评测和研究员交付物已随集成分支推送；
- 两个本地未跟踪的 v6 临时路径没有提交：
  - `outputs/.tmp-v6-blind-747f3a6e313d463cb19c2b7fbab01671/`
  - `outputs/.v6_tmp_path.txt`

## 8. 后续团队协作建议

在 Phase 2 集成基线正式合入 `main` 前，后续开发应从远端集成分支创建短期功能分支：

```bash
git fetch origin
git switch phase2-integrated
git pull --ff-only
git switch -c feat/<module>-<topic>
```

协作时注意：

1. 新分支的 PR 目标统一设为 `phase2-integrated`，避免继续向三个旧成员分支追加互相不可见的提交；
2. 不删除三个源分支，至少保留到 Phase 2 验收结束，以便追溯原始实现和冲突来源；
3. 新增 Alembic 迁移必须从 `0014_phase2_integrated_heads` 向后串行，不能再从三个 `0013` 分支头派生；
4. Graph RAG 现为默认启用能力，调整阈值前应同时更新盲标评测、消融结果和激活决策；
5. Agent 批量契约、人工闸门、单公司单逻辑、未来信息防泄漏仍是集成版本的产品红线；
6. 在线代码不得导入 `analytics`，新增数据刷新能力应继续走离线管道或独立任务。

## 9. 回退与问题定位

因为源分支保持不变，出现问题时可以先按能力来源定位：

| 问题类型 | 优先对照分支/提交 |
| --- | --- |
| Graph RAG 召回、路径或评测 | `phase2-graph-rag-p0` / `5256fa3` |
| Agent 批量契约、指标或复核流程 | `phase1_agent` / `be4e4e9` |
| 排序先验、主题排序、完整产品页面 | `feature/full-product-snapshot-20260830` / `1c7bf33` |
| 第一次合并冲突 | `6795f44` |
| 第二次合并及集成兼容修复 | `60a3098` |

已经推送的共享分支不应使用 `reset --hard` 或 force push 回退。如需撤回完整产品快照合并，应创建新的 revert 提交：

```bash
git revert -m 1 60a3098
```

若还需撤回 Agent 合并，再在前一步 revert 之后继续：

```bash
git revert -m 1 6795f44
```

执行任何回退前都必须先在独立分支验证数据库迁移、OpenAPI 与前端路由，避免代码回退后数据库仍停留在集成 head。

## 10. 最终结论

本次合并不是把三个目录简单叠加，而是完成了产品规则、Agent 契约、Graph RAG、排序 RAG、数据库迁移、前端路由和工程边界的统一。当前 `phase2-integrated` 可以作为 Phase 2 后续开发与验收的共同基线：Graph RAG 已正式开启，Agent 与图文检索链路已接通，完整产品页面和真实操作页面并存，所有强制工程门禁通过。
