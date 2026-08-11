# AI Investment Copilot

主动权益投资逻辑智能协作平台。以**投资逻辑（Investment Thesis）**为核心业务对象，把研究员的投资观点转化为可验证的结构化卡片，并将后续事实、事件和指标变化持续关联到具体假设，形成可追踪、可复核、可复盘的研究过程。

需求基线：`docs/product/AI Investment Copilot 产品需求文档（PRD）V1.2.docx`
数据基线：`docs/data/数据分析交付包/`

## 产品边界（写代码前必须先读）

这些不是建议，是硬约束。违反其中任何一条的 PR 会被直接驳回。

| 约束 | 含义 | 来源 |
| --- | --- | --- |
| 不出交易指令 | 系统输出候选信号与状态建议，绝不产生买卖/评级/调仓指令 | PRD 1.4 / DA-AC-08 |
| 人工闸门 | AI 产出一律为草稿或候选；正式状态变更必须由负责人确认并填原因 | PRD 5.4 / FR-S-002 |
| 数值由程序算 | 预期差、同比环比、趋势、同业分位一律由 `app/calc` 确定性计算，AI 只解释结果 | PRD 10.5 / FR-V-002 |
| 结论必须可追溯 | 任一正式结论可回溯到原文定位、数据版本、模型版本、提示词版本 | FR-V-005 / DA-AC-07 |
| 禁止未来信息 | 事实发生 / 披露 / 入库 / 生成四类时间分开存储，标签只能在窗口结束后生成 | DQ-003 / DQ-006 |
| 历史不可改写 | 版本快照冻结当时可得信息，口径变更走新版本而不是覆盖 | PRD 5.3 |

## 仓库地图

```
app/          后端单体（按模块划分所有权，见下表）
analytics/    数据分析与 Alpha 验证（离线，不参与线上请求）
contracts/    跨模块契约：JSON Schema、OpenAPI、事件定义（改动需双方评审）
web/          前端应用
alembic/      数据库迁移
tests/        unit / integration / contract
docs/         需求与设计基线、架构说明、ADR、协作规范
deploy/       本地与试点环境编排
scripts/      开发与运维脚本
real_data/    真实公开披露数据与验证报告（公告清单、定期报告、行情）
```

`real_data/` 里是九家上市公司的公开披露数据，已纳入版本控制
（[ADR-0006](docs/adr/0006-公开披露数据纳入版本控制.md)），目的是让团队复算同一批数字。
**非公开信息、带授权限制的内容、个人信息、凭证仍然禁止提交。**

最新验收结论见 [MVP 验收报告-三行业九公司](docs/data/MVP验收报告-三行业九公司.md)。

完整的本地安装、PostgreSQL/Redis 启动、DeepSeek 配置、API 调用、前端联调和九公司
实验复算步骤见 [使用手册](USAGE.md)。

## 模块

每个模块一个 README，写清职责、边界、对外接口和验收要点。模块边界由 `.importlinter` 在 CI 中机器检查，不依赖人肉评审。

| 模块 | 职责 | 对应 PRD 层级 | README |
| --- | --- | --- | --- |
| `app/core` | 配置、枚举、时间语义、异常等全仓公共约定 | 横切 | [README](app/core/README.md) |
| `app/db` | ORM 模型与仓储；数据资源层唯一入口 | 数据资源层 | [README](app/db/README.md) |
| `app/calc` | 确定性计算与状态规则引擎，纯函数、零 IO | AI 与规则层（规则侧） | [README](app/calc/README.md) |
| `app/ingest` | 文档解析、切片、去重、引用定位 | 数据资源层 | [README](app/ingest/README.md) |
| `app/ai` | 模型网关、提示词、JSON 契约校验与降级 | AI 与规则层（模型侧） | [README](app/ai/README.md) |
| `app/services` | 业务编排：卡片、证据、状态、复核、版本、审计 | Investment Thesis Engine | [README](app/services/README.md) |
| `app/api` | HTTP 接口、鉴权、权限过滤、DTO 出入 | 用户交互层 | [README](app/api/README.md) |
| `app/schemas` | API 出入参 Pydantic 模型 | 用户交互层 | [README](app/schemas/README.md) |
| `app/workers` | 异步任务：文档处理、变化处理、复核日扫描 | 应用层 | [README](app/workers/README.md) |
| `analytics` | 数据管道、评测集、候选信号实验 | 数据分析交付包 | [README](analytics/README.md) |
| `web` | 工作台、逻辑卡片、变化雷达、复核中心 | 用户交互层 | [README](web/README.md) |
| `contracts` | 跨模块契约的单一事实来源 | 横切 | [README](contracts/README.md) |
| `alembic` | 数据库迁移 | 数据资源层 | [README](alembic/README.md) |
| `tests` | 测试分层与夹具 | 横切 | [README](tests/README.md) |
| `deploy` | 环境编排 | 基础设施层 | [README](deploy/README.md) |
| `scripts` | 开发运维脚本 | 横切 | [README](scripts/README.md) |

架构全貌与分层依赖规则见 [`docs/architecture/README.md`](docs/architecture/README.md)。

## 快速开始

下面是 macOS/Linux 的最短路径；Windows PowerShell 以及完整产品链路见
[USAGE.md](USAGE.md)。

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env

make hooks      # 提交时自动跑门禁，省掉「CI 红了再推一次」
make check      # 格式 + 静态检查 + 分层契约 + 类型 + 测试，约 1 秒
```

未接数据库也能跑：`make check` 中的单元测试只依赖纯函数模块，不需要 PostgreSQL。集成测试需要本地库，见 [`deploy/README.md`](deploy/README.md)。

## 协作方式

私有仓库 + 主干开发。流程按「机器能查的绝不让人重复勾选」设计：

- `main` 是唯一集成分支，受保护，只能通过 PR 合入。**这是唯一的硬要求。**
- **默认不需要 approve**，CI 绿了自己合。只有 `contracts/`、`alembic/versions/`、`.importlinter`、`docs/product|data/` 这四类改错难回退的路径需要 1 个 approve。
- 格式、分层依赖、类型、迁移 head 数量由 `make check` 与 CI 检查，约 1 秒。装了 `make hooks` 后提交时自动跑。
- 分支命名、PR 大小、`Refs:` 编号都是建议，不作为驳回理由。
- 不开长期并行的功能大分支。未完成能力用配置开关藏在主干里。

会被驳回的只有上面那张产品边界表里的六条。

- 日常操作：[`CONTRIBUTING.md`](CONTRIBUTING.md)
- 完整规范：[`docs/collaboration/README.md`](docs/collaboration/README.md)
- **接入远端 / 新成员配环境**：[`docs/collaboration/远端接入手册.md`](docs/collaboration/远端接入手册.md)

## 免责声明

`docs/data/数据分析交付包/业务样例包/` 全部为虚构演示数据，不构成投资建议。带 `is_illustrative=true` 的数据禁止用于真实投资结论。
