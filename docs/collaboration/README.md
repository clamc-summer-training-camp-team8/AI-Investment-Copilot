# 协作规范

模型：**私有 Git 仓库 + 主干开发 + 模块负责人评审**。决策背景见 [ADR-0003](../adr/0003-主干开发与模块负责人评审.md)。

核心原则：不同成员负责不同模块，但所有代码通过同一个受保护的 `main` 集成。不存在长期并行的功能分支。

## 1. 角色与模块所有权

所有权在 `.github/CODEOWNERS` 中生效。一个模块必须有且仅有一个主负责人（决策与评审责任），可以有备份负责人。

| 角色 | 主要模块 | 职责 |
| --- | --- | --- |
| 架构负责人 | `docs/architecture`、`contracts`、`.importlinter`、CI | 分层依赖、跨模块契约、工程门禁 |
| 逻辑引擎负责人 | `app/services`、`app/db`、`alembic` | 核心对象、状态机、版本、审计、迁移 |
| 规则计算负责人 | `app/calc`、`app/core` | 确定性计算、阈值规则、时间语义 |
| AI 能力负责人 | `app/ai`、`contracts/ai` | 抽取、影响分析、提示词与模型版本、降级 |
| 数据管道负责人 | `app/ingest`、`analytics` | 解析、切片、去重、指标管道、评测与实验 |
| 应用接口负责人 | `app/api`、`app/schemas`、`app/workers`、`contracts/api` | 接口、权限过滤、异步任务 |
| 前端负责人 | `web` | 工作台、卡片、变化雷达、复核中心 |
| 产品负责人 | `docs/product`、`docs/data` | 需求基线、验收口径、数据缺口关闭 |

一人可兼多角色。填写实际人员时改 `CODEOWNERS`，本表同步更新。

## 2. 分支

| 分支 | 说明 |
| --- | --- |
| `main` | 唯一集成分支。受保护，禁止直接推送与 force push，始终可运行 |
| `<type>/<module>-<slug>` | 特性分支，短生命周期，建议 3 天内合回 |

`type` 取值：`feat`、`fix`、`refactor`、`docs`、`test`、`chore`、`perf`。
`module` 用模块短名：`core`、`db`、`calc`、`ingest`、`ai`、`services`、`api`、`workers`、`analytics`、`web`、`contracts`、`infra`。

示例：`feat/calc-invalidation-window`、`fix/ingest-pdf-locator`、`docs/arch-layering`。

分支超过一周未合并，需在 PR 里说明原因或拆小。长期分支是这套协作模式要防的主要失败模式。

## 3. 提交信息

Conventional Commits：

```
<type>(<module>): <简述>

<可选正文：为什么这么改，而不是改了什么>

Refs: FR-V-001, DQ-003
```

正文关联需求编号（`FR-*`、`DQ-*`、`GAP-*`、`DA-AC-*`）便于追溯验收项。

## 4. PR 流程

1. 从最新 `main` 切分支。
2. 本地跑 `make check`，通过后再推。
3. 开 PR，填模板。标题同提交信息格式。
4. CI 通过 + CODEOWNERS 指定的负责人 approve。
5. squash merge 进 `main`，删除远端分支。

评审要求：

| 改动范围 | 需要的 approve |
| --- | --- |
| 单模块内部 | 该模块负责人 |
| 跨模块 | 涉及的每个模块负责人 |
| `contracts/` | 生产方 + 消费方负责人 |
| `docs/architecture/`、`.importlinter` | 架构负责人 |
| `alembic/versions/` | 逻辑引擎负责人 |
| `docs/product/`、`docs/data/` 基线文档 | 产品负责人 |

PR 保持小。超过约 400 行改动（不含生成文件与文档）建议拆分。评审者对读不完的 PR 有权要求拆分。

紧急修复可以先合再补 approve，但必须在 24 小时内取得评审记录，并在 PR 里说明原因。

## 5. 评审关注点

按优先级：

1. **产品红线**。是否绕过人工闸门？是否让 AI 产出关键数值？是否引入未来信息？是否覆盖历史版本？这四类问题一律阻断合并。
2. **模块边界**。是否引入反向依赖？是否绕过 services 直连数据库？是否在 `analytics` 里另写一套计算口径？
3. **可追溯性**。正式结论是否带原文定位、数据版本、模型版本、提示词版本？状态变更是否留审计？
4. **测试**。阈值类逻辑是否覆盖达到 / 接近 / 未达到 / 数据缺失四种情形？
5. 可读性与命名。

评论用途分级：`must` 阻断合并，`should` 建议修改，`nit` 可忽略。写清哪一类，避免评审者与作者对严重程度理解不一致。

## 6. 数据库迁移

- 一个 PR 最多一个 alembic head。
- 迁移必须可回退，`downgrade` 不允许留空。
- 涉及历史数据口径的改动：新增版本，不原地覆盖（PRD 5.3 / 指标管道要求）。
- 两个 PR 同时加迁移时，后合并者负责 rebase 重新生成 revision 链。

## 7. 需求基线与文档

`docs/product/` 与 `docs/data/` 是需求基线，只由产品负责人更新，改动需说明版本号变化。工程侧的理解和补充写在 `docs/architecture/` 或模块 README 里，不改基线文档。

模块职责变化时，同步改该模块 README 与根 README 的模块表。README 与代码不一致视为缺陷。

## 8. 远端仓库配置

本地仓库已初始化，默认分支为 `main`，历史从架构基线提交开始。接到私有远端后：

```bash
git remote add origin <私有仓库地址>
git push -u origin main
```

然后在远端配置 `main` 的分支保护（以下为 GitHub 术语，GitLab/Gitea 对应设置项类似）：

- Require a pull request before merging
- Require approvals：1（跨模块改动依赖 CODEOWNERS 自动补充评审人）
- Require review from Code Owners
- Require status checks to pass：CI 的 `lint`、`arch`、`test` 三个 job
- Require linear history
- 禁止 force push、禁止删除分支
- 管理员同样受限（Do not allow bypassing）

**分支保护开启前不要开始并行开发。** 没有保护的 `main` 加上多人分工，会在几天内退化成各写各的，正是这套模型要防的失败模式。

私有仓库的成员权限建议：负责人 `write`，仅需查看的角色 `read`，仓库管理 `admin` 限一到两人。

第一件事是把 `.github/CODEOWNERS` 里的 `@arch-owner` 等占位符替换成实际账号或团队名，并同步更新本文第 1 节的角色表。占位符状态下 code owner 评审无法生效。

## 9. 新成员上手

1. 读根 `README.md` 的产品边界表。这六条决定了什么代码会被驳回。
2. 读 `docs/architecture/README.md` 与 `layering.md`。
3. 读自己模块的 README。
4. 装环境跑 `make check`，确认门禁在本地能通过。
5. 从一个 `docs` 或 `test` 类型的小 PR 开始，先把流程走通。
