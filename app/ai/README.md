# app/ai — 模型能力与编排

主要维护：AI 能力方向（问谁，不是评审权限）
PRD 层级：AI 与规则层（模型侧）

## 职责

把非结构化文本变成结构化草稿，并用受控工具为假设召回可周期获得的指标、校准候选
失效阈值。模型建议与正式业务状态严格分离。

```
ai/
├── agents/      六类业务能力及共享输入输出类型
├── graph_rag.py 可解释的投资知识图、图路径检索与 Evidence Fusion
├── skills/      五个模型任务的版本化 SKILL.md
├── tools/       周期指标目录与确定性阈值校准工具
├── data/        九家公司指标目录的版本化种子数据
├── contracts/   契约校验器及仅供本模块使用的新增 Schema
├── prompts/     提示词模板，带版本号
└── providers/   模型网关：local 规则实现 / http 外部或私有兼容端点
```

### 目录与文件放置规则

| 位置 | 当前职责 | 新代码放置原则 |
| --- | --- | --- |
| `agents/` | Thesis Draft、Event Impact、Metric Research、Metric Explain、Review 和 Evidence 校验等任务编排；`types.py` 保存当前 Agent 输入及内部运行结果 | 新增具体业务 Agent 放这里；暂不为每个 Agent 建独立子目录 |
| `skills/` | 模型任务的角色、分析规则、输入语义和结构化输出要求 | 一个模型任务对应一个 `skills/<skill-name>/SKILL.md` |
| `tools/` | `MetricCatalogTool` 负责受控候选召回，`ThresholdSuggestionTool` 负责可审计阈值校准 | 工具保持确定性，不引入 Planner、Registry 或通用 BaseTool 框架 |
| `data/` | 3 个行业、9 家公司、19 个周期指标和来源可得性 | 目录改动必须更新版本与核验日期；不在这里保存生产观测值 |
| `contracts/` | 优先加载全局 `contracts/ai/`，再加载本模块新增 Schema，保存 `ValidationOutcome` | 暂不把所有 DTO 机械迁入；若稳定跨模块 DTO 后续明显增多，再单独评估拆分 |
| `providers/` | local、mock 和 HTTP 模型执行适配 | 只处理模型调用与 Provider 级元数据，不编排业务状态 |
| `runtime.py` | Agent 执行、阶段迁移、验证汇总和运行审计信息 | 当前单文件仍可维护，不提前拆成 runtime 子系统 |
| `gateway.py` | Provider 选择、Schema validation 与有限修复 | 不放 Backend 业务逻辑或 Agent 任务规则 |
| `integration.py` | Agent 内部结果到 Backend-facing DTO/envelope 的稳定转换 | 当前保持兼容入口；不与 Agent 内部运行类型混写新字段 |
| `retrieval.py` | 固定 Workflow 使用的 Retriever Protocol、查询/结果类型和本地实现 | 当前不是 Agent Tool；未来 HistoricalRagTool 可以封装它，但不迁移 RAG 内部算法 |
| `skill_catalog.py` / `prompts/` | 加载版本化 Skill 并渲染 Provider Prompt | 保持轻量加载适配，不复制 Skill 内容 |
| `observability.py` | Runtime recorder 协议和模型调用用量信息 | 保持 Runtime 支撑模块，不提前拆目录 |

当前 `app/ai/agent.py` 是兼容导出入口，已有测试仍使用它；新代码优先从 `app.ai.agents` 或具体模块导入，暂不删除兼容层。

## 五类模型任务

| 任务 | 输入 | 输出 | 来源 |
| --- | --- | --- | --- |
| 逻辑卡片生成 | 用户观点、资料正文、投资对象、行业/指标词典 | 标题、核心观点、关键假设、指标建议、风险、失效条件建议、引用 | PRD 10.1 |
| 事件影响分析 | 事件事实与元数据、Candidate Hypotheses[]、各候选的已有预期和证据 | 与全部候选一一对应的相关性、方向、强度、传导路径、建议跟踪项和引用 | PRD 10.2 |
| 假设指标推荐 | 单条假设、公司、行业、受控目录候选 | 最多 5 个直接/代理指标、来源、频率、可得性和关联理由 | Phase 1 指标增强 |
| 指标结果解释 | 确定性计算结果 | 结果与假设关系的解释 | PRD 10.3 |
| 复盘草稿 | 冻结的逻辑版本、已确认证据、指标记录、人工动作、最终结果 | 正确判断、错误假设、遗漏风险、领先信号、改进建议、引用 | PRD 10.4 |

注意“指标结果解释”的输入是**计算结果，不是原始数据**。模型解释结果对假设意味着
什么，但实际值与正式规则判定仍由程序计算。

## 九家公司周期数据目录

目录版本为 `nine-company-metric-catalog-v1`，2026-08-27 核验。公司范围如下：

| 行业 | 公司 | 已核验的高频直接经营数据 | 通用财务与市场数据 |
| --- | --- | --- | --- |
| 芯片半导体 | 中芯国际、兆易创新、北方华创 | 中芯国际季度产能利用率/晶圆出货；两家设备/设计公司以季度合同负债等代理指标为主 | 日行情；季度收入、同比、毛利率、利润、现金流、研发、存货 |
| 医药 | 恒瑞医药、药明康德、云南白药 | 药品批准/受理事件可按日轮询、按月或事件汇总；产品收入通常半年/年度披露 | 日行情；季度收入、同比、毛利率、利润、现金流、研发、存货 |
| 新能源汽车 | 比亚迪、吉利汽车、小鹏汽车 | 比亚迪/吉利月销量，小鹏月交付；比亚迪月出口与电池装机；小鹏季度汽车毛利率 | 日行情；季度/半年财务指标 |

`observation_frequency` 是数据形成频率，`polling_frequency` 是系统检查新披露的频率。
例如财报可以每日轮询，但观察值仍是季度/半年数据。可得性等级：A 为公司稳定直接披露，
B 为结构化接口或法定报告稳定获得，C 为可获得但实体匹配或披露连续性需要人工复核，D
为尚未形成稳定来源。完整字段见 `data/metric_catalog.json`。

当前仓库已有行情和财务抓取管道能够为九家公司取得日行情及财报数据；公司 IR、交易所、
药监披露的行业指标已经登记来源与频率，但实际抓取适配仍应由数据/后端模块实现，本次没有
越过 `app/ai/` 修改它们。

## AI 推荐与阈值校准

推荐链路是“SQLite 目录过滤 → 模型在候选集合内排序和解释 → Schema 校验 → 人工确认”。
模型不能生成目录外 `metric_id`，也不能把日行情代理指标当作经营事实。

阈值按以下优先级生成候选，全部要求人工确认：

1. 截止 `as_of` 已记录、可追溯且口径一致的公司指引或研究预期；
2. 至少 8 期公司自身同口径事前历史的失效侧分位数；
3. 仅在研究员显式选择时使用最近一期基线，标记低置信；
4. 否则返回 `value=None`，不让模型补猜数值。

阈值结果保存公式、样本期、来源 ID、置信度和警告。工具只给候选，不写
`hypothesis_metric_map`，也不宣布假设失效。

## 后端调用入口

```python
from datetime import date
from decimal import Decimal

from app.ai.gateway import Gateway
from app.ai.runtime import InvestmentResearchAgent
from app.ai.tools import ThresholdObservation

runtime = InvestmentResearchAgent.build(Gateway.build())

# 返回 RuntimeExecution；结构化推荐位于 run.result.outcome.payload。
run = runtime.recommend_metrics(
    security_id="002594.SZ",
    hypothesis_id="H1",
    hypothesis="新能源汽车销量增长能够持续验证终端需求",
    industry="新能源汽车",
    top_k=3,
)

# 确定性阈值入口不调用模型；不足 8 期时 value 为 None。
threshold = runtime.suggest_metric_threshold(
    observations=[
        ThresholdObservation(
            period="2025Q1",
            value=Decimal("100"),
            available_on=date(2025, 4, 30),
            source_id="exchange-disclosure",
        )
    ],
    expected_direction="越高越好",
    as_of=date.today(),
)
```

`MetricCatalogTool.from_seed(database_path=...)` 可以把同一目录落到本地 SQLite 文件，
默认使用内存数据库。SQLite 只保存 AI 指标知识目录，不复制 PostgreSQL 中的正式业务表。

## Conda base 本地启动

当前机器按要求使用 `D:\anaconda3` 的 base Python。仓库的 `scripts/dev.ps1` 目前写死
`.venv`，因此在它适配 base 之前，明天测试请分别在终端执行：

```powershell
conda activate base
cd E:\简历项目\产品\AI-Investment-Copilot\AI-Investment-Copilot
$env:DEBUG = "true"

# 首次或迁移更新后执行；Docker Desktop 需已启动。
& "C:\Users\17231\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe" compose -f deploy\docker-compose.local.yml up -d
python -m alembic upgrade head

# 终端 1：API
python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000

# 终端 2：异步 worker
python -m arq app.workers.settings.WorkerSettings

# 终端 3：前端
cd web
& "C:\Users\17231\AppData\Local\Programs\nodejs\node.exe" .\node_modules\vite\bin\vite.js --host 127.0.0.1 --port 5173 --strictPort
```

验收地址：前端 `http://127.0.0.1:5173`，API 基础健康检查
`http://127.0.0.1:8000/health`，完整依赖检查 `http://127.0.0.1:8000/health/ready`。

## AI 质量规则（PRD 10.5）

四条，逐条对应实现要求：

1. **事实结论必须有引用；无法引用时标记为推断或不确定。** 输出 Schema 中引用字段对事实类结论为必填。
2. **数值计算由程序完成，模型只解释结果及其与假设的关系。** 提示词里禁止要求模型计算关键数值。评审时会查这一点。
3. **模型、提示、检索文档和生成时间均版本化。** 每次调用记录 `model_version`、`prompt_version`、`generated_at`，写入 `signal` / `evidence`。
4. **评测集覆盖不同文档类型、正反证据、口径冲突、歧义实体和历史时点。** 评测在 `analytics/evaluation/`。

## 输出必须过 Schema 校验

所有模型输出先过 JSON Schema，再进业务流程。全局契约来自 `contracts/ai/`；本次新增且
尚未接 Router 的 `metric_recommend` 契约暂放 `app/ai/contracts/schemas/`。校验失败按
`ai_status = 解析失败` 处理，进入人工流程，不抛给用户。

契约变更规则见 [ADR-0004](../../docs/adr/0004-契约优先的跨模块协作.md)。改 `contracts/ai/` 下的 Schema 需 1 个 approve，本模块内部实现的改动 CI 绿即可自合。

## 降级规则

FR-R-007：低置信结果进入人工队列，不升级提醒。

`RuleThresholds.low_confidence_cutoff`（默认 0.6）以下的输出：

- `ai_status` 标 `低置信`
- 进人工队列
- **不触发重大风险提醒**

降级规则必须可测试（FR-R-007 验收要点）。阈值在 `app/core/config.py`，不硬编码。

## 模型数据与密钥

`llm_provider = local` 时使用规则实现，不外发任何数据。这是默认值。

`http` 可指向公有云或私有兼容端点。API Key 只从服务端环境变量或密钥管理系统读取，
不得写入仓库、返回前端或出现在日志中；提示词与请求体同样不落日志明文。

`local` 提供者的存在还有一个工程价值：其他模块开发时不需要真实模型即可跑通链路，CI 也不依赖外部服务。

`llm_provider = http` 已实现 OpenAI-compatible `chat/completions` 适配器。DeepSeek
推荐配置为 `https://api.deepseek.com/chat/completions` + `deepseek-v4-flash`。配置
`LLM_ENDPOINT`、`LLM_MODEL_VERSION` 和由密钥管理系统注入的 `LLM_API_KEY` 后启用。
适配器固定结构化 JSON 输出、超时和有限重试，并由 Gateway 追加模型/提示词版本后再过
`contracts/ai/` 校验。远程端点必须使用 HTTPS（只有 localhost/回环地址可用 HTTP）。
HTTP 4xx 视为不可重试配置错误；408、429、5xx 和网络错误可重试。

## 提示词管理

- 一个任务一个模板文件，文件内声明版本号。
- 提示词改动视为发布行为，需可灰度可回滚（FR-A-002）。
- 提示词变更后需重跑评测集，在 PR 里附对比结果。没有评测对比的提示词改动不合并。

## 边界

- 不 import `app.db`、`app.services`。数据由调用方传入，结果返回给调用方。
- 不写 PostgreSQL 正式业务库；指标目录可按调用方指定路径写本地 SQLite。
- 模型不做关键数值计算；阈值工具只执行版本固定、可复算的分位数和取整规则。
- 不自行改状态。所有输出都是候选，人工闸门在 `app/services`。

Graph RAG 同样遵守该边界：图是关系库正式对象按来源、观测、语义、研究和摘要层形成的只读
投影，默认只沿已确认边进行单向跨层遍历；它只返回带原文 locator 的候选上下文、图快照和
路径解释，不创建或确认任何业务关系。实现与验收口径见
[`../../docs/architecture/Graph-RAG实现说明.md`](../../docs/architecture/Graph-RAG实现说明.md)。

默认发布策略使用 `graph-evidence-fusion-v1`：在候选池、证券、权限和时间边界内确定性融合文本、
中文 BM25 与 Graph 路径排序，并保留路径、图分、快照和分支排名。v6 专业研究员一次性盲测已
14/14 通过，因此 `RAG_GRAPH_ENABLED` 默认开启、`RAG_GRAPH_ASSIST_ONLY` 默认关闭；需要保序
兼容时仍可显式启用 assist 模式，运行时异常继续回退到文本检索。

## 测试

- `tests/unit/ai/` 用 `local` 提供者，测校验、降级、版本记录。
- `tests/contract/` 断言输出符合 `contracts/ai/` Schema。
- 效果评测不在 `tests/`，在 `analytics/evaluation/`。CI 不跑效果评测，跑的是契约与降级逻辑。
- `tests/unit/ai/test_http_provider.py` 使用 HTTPX MockTransport 验证鉴权头、结构化输出、
  瞬时失败重试和不可重试错误，不调用真实模型、不消耗额度。
