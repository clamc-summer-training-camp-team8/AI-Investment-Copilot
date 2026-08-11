# 协作规范

模型：**私有 Git 仓库 + 主干开发 + 模块负责人评审**。决策背景见 [ADR-0003](../adr/0003-主干开发与模块负责人评审.md)。

业务裁决记录（与工程流程无关，但会改变数据口径，改动前必读）：

| 文档 | 内容 |
| --- | --- |
| [20260810-导师答疑清单](20260810-导师答疑清单.md) | 待业务确认事项，A 段为阻塞项 |
| [20260811-导师裁决-事件方向标注规则](20260811-导师裁决-事件方向标注规则.md) | 事件方向标注规则裁定，GAP-004 首次关闭 |

裁决书里的规则是**业务判定**。落地代码（`analytics/pipelines/annotate_events.py`
的 `MENTOR_RULINGS`）与之绑定，改动需先更新裁决书并递增 `RULING_VERSION`——
工程侧不能单方面推翻业务裁定。

核心原则：不同成员负责不同模块，但所有代码通过同一个受保护的 `main` 集成。不存在长期并行的功能分支。

## 0. 这套流程的成本预算

当前团队 2-3 人。规则按一条原则设计：**机器能查的绝不写进清单让人重复勾选。**

| 环节 | 谁来做 | 耗时 |
| --- | --- | --- |
| 格式、分层依赖、类型、README 齐备、迁移单 head | CI 与 pre-commit hook | 约 1 秒 |
| 产品红线、业务正确性 | 人（只在有风险时） | 按需 |
| 强制 approve | 只有四类不可逆路径 | 其余为零 |

单模块改动的完整流程是：切分支 → 改 → 提交（hook 自动跑门禁）→ 推 → CI 绿 → 自己合。**不需要等任何人。**

下面每条约束都说明了「不遵守会发生什么」。凡是后果只是「风格不统一」的，都是建议而非要求。

## 1. 职责分工

分工用于知道「这块问谁」，不构成评审权限。除下表的强制评审路径外，任何人可以改任何模块。

| 方向 | 主要范围 |
| --- | --- |
| 架构与工程 | `docs/architecture`、`contracts`、`.importlinter`、CI |
| 逻辑引擎与数据 | `app/services`、`app/db`、`alembic` |
| 规则计算 | `app/calc`、`app/core` |
| AI 能力 | `app/ai` |
| 数据管道与离线分析 | `app/ingest`、`analytics` |
| 接口与前端 | `app/api`、`app/schemas`、`app/workers`、`web` |
| 产品 | `docs/product`、`docs/data` |

一人可兼多个方向。`.github/CODEOWNERS` 里只登记强制评审路径，不逐模块登记负责人——2-3 人团队里逐模块强制评审的主要产出是等待，模块边界由 `.importlinter` 在 CI 里机器检查，比人肉评审更可靠也更快。

**团队涨到 5-6 人时把模块负责人加回来。** 做法：在 `CODEOWNERS` 中按模块补 `/app/calc/ @calc-owner` 这类条目，并在远端打开 "Require review from Code Owners"。届时改动量集中在少数模块、并行冲突变多，评审的收益才会超过等待成本。

## 2. 分支

| 分支 | 说明 |
| --- | --- |
| `main` | 唯一集成分支。受保护，禁止直接推送与 force push，始终可运行 |
| 特性分支 | 短生命周期，自己起名 |

**这一条是硬要求**：`main` 受保护、改动走 PR。放开它等于回到各自维护互不兼容版本的状态，是这套协作模式存在的唯一理由。

**其余都是建议**：分支名推荐 `<type>/<module>-<slug>`（如 `feat/calc-invalidation-window`），因为好认；起了别的名字不会被驳回。建议 3 天内合回主干，理由是接口变化早暴露比晚暴露便宜，不是考核指标。

## 3. 提交信息

推荐 Conventional Commits，`<type>(<module>): <简述>`。正文写为什么这么改，比写改了什么有用。

关联需求编号（`Refs: FR-V-001`）在改动涉及验收项时很有价值，其他时候不必强求。**没有编号不影响合并。**

## 4. PR 流程

```bash
git switch -c feat/calc-invalidation-window
# 改代码，写测试
git commit -am "feat(calc): 按建立日裁剪失效判定窗口"   # hook 自动跑门禁
git push -u origin HEAD
# 开 PR → CI 绿 → 自己合
```

**默认不需要 approve。** CI 通过即可自行 squash merge。远端开 auto-merge 后可以在推完 PR 时就点上，CI 绿了自动合，不用回来盯。

只有这四类路径需要 1 个 approve，因为改错了很难回退：

| 路径 | 为什么不能自合 |
| --- | --- |
| `contracts/` | 改动的代价由消费方承担，消费方要有话语权 |
| `alembic/versions/` | 线上数据改错无法靠回滚代码挽回 |
| `.importlinter` | 放宽约束等于放宽全仓边界 |
| `docs/product/`、`docs/data/` | 验收口径变化，需确认版本号 |

其余情况想让人看时，在 PR 里 @ 对方，或开 draft PR 讨论。这是主动求助，不是流程义务。

PR 小一点评审快一点，但没有行数上限。

## 5. 评审关注点

评审存在的意义是查机器查不了的东西。CI 已经在管格式、分层依赖、类型、README 齐备、迁移 head 数量——**这些不用人再看一遍**。

人只看两类：

1. **产品红线**。是否绕过人工闸门？是否让 AI 产出关键数值？是否引入未来信息？是否覆盖历史版本？这四类会造成数据返工或合规问题，发现了就说，不管 PR 是谁的。
2. **业务正确性**。阈值逻辑覆盖了达到 / 接近 / 未达到 / 数据缺失吗？口径对不对？

评论标 `must` / `nit` 两级就够。`nit` 默认不必改。

自合的改动没有评审者，所以第 1 条靠作者自己在 PR 模板里过一遍——模板只留了这五个问题，且只要求回答有风险的那几条。

## 6. 数据库迁移

- 一个 PR 最多一个 alembic head。
- 迁移必须可回退，`downgrade` 不允许留空。
- 涉及历史数据口径的改动：新增版本，不原地覆盖（PRD 5.3 / 指标管道要求）。
- 两个 PR 同时加迁移时，后合并者负责 rebase 重新生成 revision 链。

## 7. 需求基线与文档

`docs/product/` 与 `docs/data/` 是需求基线，改动需产品负责人 approve 并说明版本号变化。工程侧的理解和补充写在 `docs/architecture/` 或模块 README 里。

模块职责变化时同步改该模块 README。README 齐备由 `tests/contract/test_repo_structure.py` 检查，内容准不准靠自觉。

**ADR 不阻塞合并。** 涉及分层依赖、模块边界、跨模块契约的决策该记下来，但先合代码、一周内补 ADR 即可。ADR 的价值在半年后被人读到，不在于合并前写完。

## 8. 远端仓库配置

> **第一次接入远端请直接看 [`远端接入手册.md`](远端接入手册.md)**，那是逐步操作清单（建组织、推送、配保护、验证、拉人），本节只是配置要点的速查。

本地仓库已初始化，默认分支为 `main`，历史从架构基线提交开始。接到私有远端后：

```bash
git remote add origin <私有仓库地址>
git push -u origin main
```

然后配置 `main` 的分支保护。**按 2-3 人团队的最小集**（GitHub 术语，GitLab/Gitea 对应项类似）：

| 设置 | 值 | 理由 |
| --- | --- | --- |
| Require a pull request before merging | 开 | 唯一的硬要求 |
| Require approvals | **0** | 默认自合，不等人 |
| Require review from Code Owners | 开 | 只对 CODEOWNERS 里那四类路径生效 |
| Require status checks to pass | `格式与静态检查`、`分层依赖契约`、`测试` | 机器门禁不放过 |
| Require branches to be up to date | 开 | 防两个 PR 分别绿、合起来红 |
| 禁止 force push / 删除分支 | 开 | 保护历史 |
| Allow auto-merge | 开 | CI 绿了自动合，不用回来点 |
| 合并方式 | 只留 squash | 主干历史干净 |

`Require approvals = 0` 配合 `Require review from Code Owners` 是关键组合：普通改动零 approve 自合，只有 `contracts/`、`alembic/versions/`、`.importlinter`、`docs/product|data/` 会因为 code owner 规则要求评审。

刻意**不开**的两项：

- **Require linear history**：会强制作者处理 rebase 冲突，squash merge 本身已经产生线性历史。
- **Do not allow bypassing（管理员受限）**：2-3 人团队需要有人能在 CI 卡死时救场。

**分支保护开启前不要开始并行开发。** 没有保护的 `main` 加上多人分工，会在几天内退化成各写各的。

成员权限：开发者 `write`，仓库管理 `admin` 限一到两人。**code owner 的 team 必须有 `write`**——只有 `read` 的成员点不了 Approve，PR 会一直等一个永远不会来的批准。

接入远端第一件事是把 `.github/CODEOWNERS` 里的 `@your-org/maintainers`、`@your-org/product` 换成实际组织名。占位符状态下 code owner 评审不生效，且 GitHub 不报错、只静默忽略——此时全仓都是自合，四类不可逆路径失去保护。改完打开该文件的 GitHub 页面确认顶部没有黄色警告条。

用 team 而不是个人用户名有两个原因：人员变动时不用改文件；team 里任何一人可批准，避免「作者不能 approve 自己的 PR」造成的死锁。**每个 team 至少两人。**

## 9. 新成员上手

完整步骤见 [`远端接入手册.md`](远端接入手册.md) 第 9 节。摘要：

1. 读根 `README.md` 的产品边界表。这六条是唯一会让改动被驳回的原因。
2. 跑 `make install && make hooks && make check`。
3. 读自己要动的模块的 README。
4. 直接开始写。第一个 PR 不用找人评审，CI 绿了自己合。

架构全貌（`docs/architecture/README.md`）和分层规则（`layering.md`）值得读，但不必在写第一行代码前读完——违反分层的话 `make check` 会在 1 秒内告诉你，比读文档快。

## 10. 什么时候该把约束加回来

这套流程是按 2-3 人调的。出现以下信号时，加回对应约束比继续省流程更划算：

| 信号 | 加回什么 |
| --- | --- |
| 团队到 5-6 人 | `CODEOWNERS` 补模块负责人条目 |
| 同一模块反复被不熟悉它的人改坏 | 该模块加 code owner |
| `main` 上出现过一次需要 revert 的产品红线问题 | `Require approvals` 提到 1 |
| 合并冲突开始频繁 | 引入 merge queue，而不是限制分支数 |

反过来，**不要因为「感觉不规范」而加约束**。每条约束都要能说出不遵守会发生什么。
