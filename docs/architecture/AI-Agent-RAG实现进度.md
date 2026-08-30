# AI Agent / RAG 实现进度

## 使用方式

每完成一个阶段，记录实现范围、验证结果、问题和下一步。每个阶段单独提交 Git，提交信息与本文件中的阶段编号对应。

## 阶段记录

### 阶段 1：AI Provider/Gateway 基础框架

状态：实现完成，测试通过，待 Git 提交。

实现内容：

- 扩展 Settings.llm_provider，支持 local、mock、http 三种方式；
- 新增 MockProvider，默认复用 local 规则，也支持注入固定 payload；
- 新增 HttpLLMProvider，按 OpenAI-compatible /chat/completions 调用私有模型；
- HTTP Provider 支持 API Key、超时和有限重试；
- HTTP Provider 使用现有 Prompt 模板，并自动补充模型版本、Prompt 版本和生成时间；
- Gateway 将 Provider 响应异常转换为“解析失败”结果，不把模型异常直接暴露给业务层；
- 新增 Gateway 单元测试。

遇到的问题：

- 当前 local.py 是规则实现，不是真实本地大模型；
- 原 Gateway.build() 只支持 local，http 分支会直接抛出“尚未实现”；
- Prompt 模板已经存在，但之前没有真实 HTTP Provider 消费它。

解决方法：

- 保持 Provider Protocol 不变，新增 HTTP/Mock 实现；
- 让业务层继续只依赖 Gateway；
- 真实 LLM 输出仍必须经过既有 JSON Schema 校验和人工闸门；
- 不在本阶段改变业务对象、数据库模型或 AI Schema。

验证结果：

- python -m py_compile app/ai/providers/http.py app/ai/providers/mock.py app/ai/gateway.py tests/unit/ai/test_gateway.py 通过；
- DEBUG=true python -m pytest tests/unit/ai/test_gateway.py -q：2 passed；
- 当前环境未安装 Ruff，未能执行 Ruff 检查；
- 项目现有 .env 的 DEBUG=release 与布尔型 Settings 冲突，测试使用临时环境变量覆盖，未修改 .env；
- HTTP Provider 的真实网络调用和私有模型响应格式尚未现场验证，阶段 2 前仍需使用 MockTransport 或真实测试端点验证。

### 阶段 2A：公告正文采集和文档标准化

状态：实现完成，测试通过，待 Git 提交。

实现内容：

- 新增 pp/ingest/notices.py；
- 将公告列表记录标准化为 NoticeRecord；
- 支持从详情 URL 获取 HTML；
- 支持识别详情页中的 PDF 链接并下载原 PDF；
- 支持直接返回 PDF 的情况；
- 原始 HTML/PDF 按公告 ID 缓存，不覆盖已缓存文件；
- HTML 提取排除 head、script、style、nav、footer 等非正文区域；
- 输出复用 ParsedDocument / RawSegment，保留发布时间、文档类型、页码和 parser_version；
- 注入 httpx.MockTransport，可以脱离网络测试采集逻辑。

遇到的问题：

- 初版 HTML 提取把 title、导航和页脚误当成正文；
- 公告列表本身没有正文，必须把详情 URL 抓取和原文缓存作为独立步骤；
- PDF 与 HTML 详情页的返回类型不固定。

解决方法：

- 增加非正文标签过滤；
- 根据响应 Content-Type 和 PDF 文件头判断正文类型；
- HTML 先缓存，再尝试提取 PDF，失败时回退为 HTML 正文解析；
- 通过 MockTransport 固化没有网络时的测试路径。

验证结果：

- python -m pytest tests/unit/ai/test_gateway.py tests/unit/ingest/test_notices.py -q：4 passed；
- git diff --check 通过；
- 真实网站抓取尚未执行，需后续在获得数据源访问和使用确认后做小批量验证。

### 阶段 2B：可替换 Retriever 和 RAG 检索基线

状态：实现完成，测试通过，待 Git 提交。

实现内容：

- 新增 Retriever Protocol；
- 新增 RetrievalDocument、RetrievalQuery、RetrievedChunk、RetrievalResult；
- 新增确定性 KeywordRetriever，作为不依赖额外向量数据库的 RAG 基线；
- 检索支持 security_id、s_of 时间上界和 llowed_visibility 权限过滤；
- 返回原文 document_id、locator、发布时间、来源和得分；
- 后续 Chroma/pgvector 只需替换 Retriever 实现，不改变 Agent 契约。

遇到的问题：

- 当前依赖中没有 Chroma、FAISS 或 pgvector；
- 如果先绑定具体向量库，会把基础设施选择和业务过滤规则混在一起。

解决方法：

- 先实现可复现关键词检索，冻结 RAG 的输入输出和权限/时间过滤语义；
- 等真实数据规模和部署方式确认后，再增加向量检索实现。

验证结果：

- 	ests/unit/ai/test_retrieval.py：2 passed；
- 已验证证券过滤、未来信息过滤、权限过滤和 locator 返回。

### 阶段 3：投资逻辑变化 Agent 最小编排

状态：实现完成，测试通过，待 Git 提交。

实现内容：

- 新增 AgentEvent、CandidateHypothesis、AgentImpact 和 AgentRunResult；
- 新增 InvestmentLogicChangeAgent；
- Agent 按候选假设分别检索上下文，再调用 Gateway 的 event_impact；
- 将检索到的段落、目标假设和 locator 作为模型上下文；
- Gateway/Provider 增加可选 context，兼容原有 Worker 调用；
- Agent 不写数据库、不发布 Thesis、不直接改变正式状态；
- 新增未来信息过滤和 Agent 编排测试。

遇到的问题：

- 原 event_impact 接口只有单条事件文本，Prompt 中的候选逻辑和上下文没有真实传入；
- 如果 Agent 直接依赖数据库，会破坏 pp.ai 与业务服务的分层边界。

解决方法：

- 以可选 context 扩展 Provider 接口，保持旧调用兼容；
- Agent 接收候选假设和 Retriever，由后端服务负责数据库召回；
- 输出保留 ValidationOutcome，后端继续负责保存候选 Evidence 和人工闸门。

验证结果：

- 	ests/unit/ai/test_gateway.py tests/unit/ai/test_retrieval.py tests/unit/ai/test_agent.py tests/unit/ingest/test_notices.py：8 passed；
- 已验证 Agent 能将检索结果传递到事件影响调用；
- 已验证 s_of 时间上界不会把未来文档送进上下文。

## 后续阶段占位

### 阶段 2：公告正文采集和文档标准化

目标：从公告 CSV 的详情 URL 获取 HTML/PDF，缓存原文件，生成带 locator 的标准文档和段落。

### 阶段 3：最小 RAG

目标：建立 Retriever 接口，先实现本地持久化向量检索，保留公司、时间、来源和权限过滤。

### 阶段 4：投资逻辑变化 Agent

目标：编排 Thesis 召回、RAG、事件影响分析、确定性计算、引用校验和人工确认。

### 阶段 5：真实数据 Demo 与评测

目标：使用云南白药验证公告 RAG，使用储能案例验证完整投资逻辑变化闭环。

### 阶段 4：补充 AI 初始 Thesis/Hypothesis 生成边界与 Agent 规划

状态：规格补充完成，代码待实现。

主要内容：
- 明确初始投资逻辑和假设可以由 AI 生成，但产物是待人工审核的 Thesis Draft/Hypothesis Candidate。
- 增加 `documents only` 输入模式，后续让 AI 可从公告/研报资料归纳初始观点。
- 明确正式方向、预期值、失效阈值和发布状态仍需人工确认。
- 规划 4 个业务 Agent 能力：`ThesisDraftAgent`、`InvestmentLogicChangeAgent`、`EvidenceAgent`、`ReviewAgent`；MVP 优先实现前两个。

当前缺口：现有草稿接口仍要求 `view`，且尚未把 RAG 检索结果接入 Thesis 草稿生成；下一阶段补 `ThesisDraftAgent` 和 documents-only 流程。
### 阶段 5：ThesisDraftAgent 与 RAG 草稿编排

状态：Agent 核心实现完成，API 接入待继续。

主要内容：
- 新增 `ThesisDraftAgent`，支持 `view + documents`、`documents only` 和 `view only` 三种调用方式。
- Agent 先把来源片段加入 Retriever，再按证券、时间和权限检索，向 Gateway 传递带 locator 的片段。
- 新增 `ThesisDraftRunResult`，同时保留检索结果和 AI Schema 校验结果，便于后端保存引用和诊断。
- Agent 不写数据库、不发布 Thesis，不填写正式预期值和失效阈值。
- 新增资料生成草稿测试；AI 单元测试结果：7 passed。

遇到的问题：现有 `/theses/drafts` 请求模型仍要求 `view`，接口内部仍传入空 `segments`，因此 documents-only 还未贯通 HTTP API。

解决/下一步：下一阶段扩展 `ThesisDraftIn`，允许传入来源片段或文档 ID，并由 API/服务层构造 `RetrievalDocument` 后调用 `ThesisDraftAgent`；保留 view 作为可选人工提示。
### 阶段 6：EvidenceAgent 证据边界校验

状态：实现完成，未接入后端持久化。

主要内容：
- 新增 `EvidenceAgent`，只校验 Agent 输出的 citations 是否来自本次检索结果或事件原始 locator。
- 支持校验字符串引用和 `{locator: ...}` 引用格式。
- 无引用、引用越界或存在 `unsupported_claims` 时标记为需要人工复核。
- 新增 `EvidenceValidation` 结果对象，并支持批量校验 `AgentRunResult`。
- 不修改数据库、不创建正式 Evidence、不改变 Thesis 状态，保持与后端职责分离。

验证结果：AI 单元测试 8 passed。

下一步：等待后端同学确定 Evidence 持久化字段后，由后端适配 `EvidenceValidation`，本支线继续完善 RAG 评测样例和真实模型兼容性测试。
### 阶段 7：Agent 与后端职责边界冻结

状态：完成。

主要内容：
- 明确本支线只维护 `app/ai/`、AI 单元测试和架构文档。
- 明确 Agent 负责检索、模型调用、结构化候选结果和证据校验，不写数据库、不发布 Thesis、不改变正式状态。
- 明确后端负责事件触发、结果持久化、状态变更和 API 返回。
- 采用“一个编排入口 + 可替换能力模块”设计，后端通过稳定输入输出契约接入。

本阶段按要求暂不修改 RAG 存储、向量库和检索元数据；待后续单独确认后再评估。
### 阶段 8：生产级能力路线补充

状态：规格补充完成，工程实现待分阶段推进。

主要内容：
- 补充从 AI 能力 MVP 到生产系统的目标架构。
- 增加 Agent Runtime、运行状态、任务队列、幂等、重试、恢复和可观测性规划。
- 确定 RAG 生产化方向为 PostgreSQL + pgvector，当前仍保留 KeywordRetriever 基线。
- 增加文档治理、证据完整性评分、模型调用审计、评测回归、安全和部署计划。
- 明确 P0-P4 实施顺序，以及当前支线不修改后端数据库/API/队列的边界。

本阶段只更新规格和计划，没有宣称生产级能力已经完成。
### 阶段 9：统一 Agent 编排入口与运行状态

状态：AI 能力层实现完成，后端持久化待接入。

主要内容：
- 新增 `app/ai/runtime.py` 中的 `InvestmentResearchAgent`，统一调用 ThesisDraftAgent、InvestmentLogicChangeAgent 和 EvidenceAgent。
- 新增 `RuntimeExecution`，记录 `run_id`、任务类型、开始/结束时间、结果、证据校验和错误信息。
- 支持 `created`、`retrieving`、`generating`、`verifying`、`completed`、`needs_human_review`、`failed` 状态语义。
- 低置信度、解析失败、引用校验异常不会伪装成完成结果。
- 运行时只返回结构化执行结果，后端可在外层负责持久化、队列和状态变更。

验证结果：AI 单元测试 10 passed。

下一步：补充证据完整性评分和评测样例；待后端确定运行记录字段后，再由后端持久化 `RuntimeExecution`。
### 阶段 10：证据完整性评分

状态：AI 能力层实现完成，后端持久化待接入。

主要内容：
- 在 `EvidenceAgent` 中新增 `EvidenceGrade`。
- 根据有效引用数量、来源数量和事件时间新鲜度计算可解释分数。
- 输出 `passed`、`score`、`missing`、`stale_count` 等字段，便于后端进入人工复核或降级流程。
- 保留原有引用越界和 `unsupported_claims` 校验，不把评分结果直接当作正式 Evidence。

验证结果：AI 单元测试 11 passed。

下一步：补充固定评测样例，覆盖支持、冲突、中性、资料不足和过期证据场景。
### 阶段 11：证据验证与传导逻辑汇报文档

状态：完成。

新增 `AI证据与传导逻辑说明.md`，记录：
- 事实证据的准确性、可回溯性、时效性、实体匹配和权限验证。
- 事实到业务变量、指标和投资假设的传导链路。
- `evidence_score` 与 `impact_confidence` 的区别。
- 当前代码已实现和未实现的边界。
- 后续修改 AI/RAG 代码时必须同步维护文档的规则。

该文档用于组会汇报和后续实现对照。

### 阶段 13：将证据评分接入统一运行时

状态：完成。

主要内容：
- `RuntimeExecution` 新增 `evidence_grades`。
- `InvestmentResearchAgent.analyze_event()` 在引用校验后自动计算每个影响结果的 `EvidenceGrade`。
- 任一引用校验或证据完整性评分未通过时，运行状态进入 `needs_human_review`。
- 保持评分结果只作为候选分析和人工复核依据，不直接写数据库或改变正式 Thesis 状态。

验证结果：AI 单元测试 11 passed。
### 阶段 14：证据一致性与冲突检查

状态：AI 能力层实现完成，后端持久化待接入。

主要内容：
- 修正 `EvidenceAgent` 的静态方法定义，确保统一 Runtime 调用稳定。
- 新增 `EvidenceConsistency`，检查目标实体是否匹配检索片段。
- 检查模型抽取的事实是否能在引用上下文中找到基本文本支持。
- 检测引用上下文中同时出现的正向和负向线索，标记冲突证据。
- 统一 Runtime 在证据一致性存在缺口时进入 `needs_human_review`。

验证结果：AI 单元测试 12 passed。

说明：事实一致性检查是保守的词元重合基线，不等同于语义事实核验；后续可由真实数据和模型评测替换或增强。
### 阶段 15：真实公开数据 AI 适配

状态：完成。

主要内容：
- 合并 `origin/feat/mvp-closed-loop` 提供的真实公开数据，保持在本地 `feat/ai-framework`，未推送远程。
- 新增只读适配层，将公告、事件标注、Thesis/Hypothesis 转换为现有 Agent/Retriever 契约。
- 保留证券代码前导零、披露时间、公告 ID、PDF URL 对应关系和可回溯 locator。
- 将数据集的“削弱”统一映射为现有契约的“冲突”，不修改全局受控枚举。
- 当前公告数据只有标题和 URL，检索来源明确标记为 `cninfo-title`，不把标题冒充 PDF 正文。

数据检查结果：
- 公告元数据 3784 条；事件标注 3784 条；Thesis 45 条；Hypothesis 135 条。
- 事件标注包含双标注方向、是否一致、是否待裁决和训练/测试切分字段。
- 当前金标主要由程序规则预标注，且报告已提示规则与候选方法可能存在同源偏差，不能直接作为真实模型效果结论。

验证结果：AI 单元测试 16 passed，其中真实数据适配测试 4 passed。

### 阶段 16：混合检索、运行降级与后端交接契约

状态：AI 能力层完成；向量持久化和任务持久化由后端/数据支线接入。

主要内容：
- 新增 `HybridRetriever`，用加权倒数排名融合全文和向量 Retriever，合并后再次执行证券、时间和权限过滤。
- 混合检索不绑定具体向量数据库；后续 pgvector 实现只需遵循现有 Retriever 接口。
- Runtime 增加 `degraded` 状态、降级原因、Schema 名称以及模型/Prompt/检索版本记录。
- 无候选假设不再误报完成；Provider/Schema 失败标记为可重试降级，非预期异常才标记 `failed`。
- 修正事件原始 `evidence_locator` 的证据识别：它是本次新事件的主引用，不应因顶层没有 citations 而被误判为无证据。
- 新增可 JSON 序列化的 `ai-runtime-envelope-v1`，供后端保存候选结果和验证明细。
- 新增 `AI后端接入契约.md`，冻结数据流、状态语义和双方职责边界。
- 单元测试显式禁用 `.env`，避免本地真实模型配置污染离线测试。

验证结果：AI 单元测试 20 passed；未调用真实 DeepSeek API，未产生外部费用。
### 阶段 17：P1 指标解释与复盘草稿 Agent

状态：AI 能力层完成；业务 API 和持久化仍由后端支线接入。

主要内容：
- 新增 `MetricExplainAgent`：只消费 `app.calc` 的确定性结果并解释含义，不重新计算、修正或推导关键数值。
- 新增 `ReviewAgent`：只汇总输入的已有记录，区分支持、冲突和待确认事项，不引入外部事实、不改变正式 Thesis 状态。
- 新增 `metric_explain`、`review_draft` Prompt、Provider/Gateway 方法和 JSON Schema。
- 两项能力接入统一 Runtime，并记录模型、Prompt 和 Schema 版本。
- Local/Mock/HTTP Provider 均保持同一契约；使用 MockTransport 验证 DeepSeek/OpenAI-compatible 请求形状，不进行真实网络调用。
- 使用一条提交的真实事件、对应真实 Thesis/Hypothesis 跑通数据适配到 Runtime 的离线链路。

验证结果：AI 单元测试 24 passed；全部 `app/ai` Python 文件编译通过；`git diff --check` 通过。
### 阶段 18：全项目回归与本地 DeepSeek 配置隔离

状态：完成。

主要内容：
- DeepSeek 配置保存在本机被 Git 忽略的 `.env.deepseek`，密钥不进入代码、文档或提交。
- 默认 `.env` 继续使用 `local` 且不配置外部端点，避免测试、队友开发和未授权资料在无感知情况下外发。
- DeepSeek profile 使用官方 OpenAI-compatible 端点和 `deepseek-v4-flash`；本阶段仅验证配置可读取和离线 HTTP 协议，不发起真实付费调用。
- 全项目非数据库测试通过，确认真实数据合并和 AI 改动没有破坏现有闭环。

验证结果：
- `python -m pytest -q --ignore=tests/integration/db`：203 passed。
- 数据库约束测试 4 项未执行：当前环境缺少 `psycopg` 且未启动 PostgreSQL；这是环境依赖，不是 AI 测试失败。
- AI 单元测试：24 passed。
- 工作区无待提交代码；所有提交均只在本地分支，未 push。
### 阶段 19：Agent 能力目录拆分

状态：完成。

主要内容：
- 将原来 343 行的 `app/ai/agent.py` 按职责拆分为 `app/ai/agents/` 包。
- `types.py` 只保存 Agent 共享输入、输出和值对象。
- `thesis_draft.py`、`logic_change.py`、`evidence.py`、`metric_explain.py`、`review.py` 分别保存对应能力实现。
- 统一 Runtime 和真实数据适配层改为依赖新包，不再依赖聚合实现文件。
- 原 `app/ai/agent.py` 保留为兼容导出入口，后端和既有测试的导入路径不会失效。
- 本阶段只移动现有逻辑，没有修改 Prompt、Schema、运行状态、评分公式和业务行为。

遇到的问题：
- 完整目标结构还包含 `retrieval/`、`embeddings/` 和 `pgvector.py`，但当前任务只拆分已有 Agent；在真实 Embedding/PgVectorRetriever 尚未实现前，不创建空壳文件冒充完成。

解决方法：
- 先完成可独立验证的 Agent 结构重构；检索与 Embedding 在下一阶段实现真实能力时再拆分。
- 新增兼容性测试，断言旧入口与新模块导出的是同一个实现类。

验证结果：重构前 AI 单元测试 24 passed；重构后 25 passed；全项目非数据库测试 204 passed；全部 `app/ai` Python 文件编译通过。当前环境未安装 Ruff，因此未执行 Ruff 检查。

### 阶段 20：Graph RAG 结构化关系检索

状态：实现完成，默认关闭，等待真实问题金标对照评测后决定试点流量。

主要内容：

- 新增 `investment-graph-rag-v1`，显式表示证券、逻辑、假设、业务变量、指标、观测、事实、事件、证据、文档和原文片段。
- 从现有 UnitOfWork 构建只读图投影，不引入第二事实源；默认只纳入已确认指标映射和证据关系。
- 支持从假设沿“变量—指标—事实—原文”路径召回词面不重合的文本，并融合原文本检索分数。
- 每个结果返回节点类型、关系方向、边的原文定位和可读路径解释；事实或图节点不能冒充引用。
- 路径上的每个节点都执行证券、权限标签和披露时间过滤，未确认边默认不可遍历。
- Worker 通过 `RAG_GRAPH_ENABLED` 显式启用，默认关闭；Graph Retriever 可包装任意现有 Retriever，不实现 Agentic RAG 的循环或任务规划。
- 新增本地复现命令 `python -m scripts.run_graph_rag` 和完整实现说明。

验证结果见 `tests/unit/ai/test_graph_rag.py` 与 `tests/unit/services/test_graph_rag.py`；全量门禁结果以本次最终验证记录为准。

### 阶段 21：Graph RAG 分层知识库

状态：实现完成，沿用默认关闭的灰度策略。

主要内容：

- Graph RAG 升级为 `investment-graph-rag-v2-layered`，显式定义原始证据、事实观测、领域语义、投资研究和聚合摘要五层。
- 节点类型只能属于指定知识层；检索路径跨层后只能持续上钻或下钻，不能借共享指标折返到其他研究对象再下钻证据。
- 构建服务加入分层构建入口和受控指标别名表，支持“营收/营业收入”“ASP/平均销售价格”等确定性对齐。
- 每次构建生成稳定 `GraphSnapshot`，记录 Schema、构建器、词表版本、时间截面、逻辑和证券范围，以及各层节点数和内容哈希。
- `as_of` 从仅在查询阶段过滤扩展为构建和查询双重过滤；命令行输出快照及完整层级路径。
- 聚合摘要层当前作为受控扩展位，不自动生成摘要，不允许未经评测的二手摘要成为正式证据。

本阶段仍不引入图数据库或 Agentic RAG 规划逻辑；关系数据库继续作为唯一事实源。

### 阶段 22：双路召回前端可解释展示

状态：完成。

主要内容：

- 候选证据冻结文本分、图分、融合分、图路径、检索版本和 Graph Snapshot 清单，不复制原文正文。
- 新增 `0012_evidence_retrieval_trace` 迁移和权限受控的证据 retrieval-trace API；旧证据安全降级为未记录。
- 证据核验页新增“双路召回依据”，显示三类得分、知识层路径、来源 locator、检索版本和快照 ID。
- 接口复用证据与来源文档权限，追踪信息不进入列表接口，不扩大数据暴露面或列表响应体。

### 阶段 23：双路融合试点加固

状态：完成。

主要内容：

- 候选逻辑在证券和权限过滤后按事件文本分、图画像分及融合分稳定排序；排序不自动淘汰逻辑。
- 排序结果、实际检索模式和 Graph Snapshot ID 写入事件审计，并返回资料处理作业结果。
- 上传完成页显示本次使用“基础规则、文本、关系图或文本＋关系图”中的哪一种模式。
- Graph Retriever 包装改为幂等：复用 Runtime 时先还原底层文本 Retriever，再挂载最新图快照，避免嵌套和版本串增长。

### 阶段 24：量化研究 MVP

状态：完成研究验证闭环；真实行情适配与组合级回测进入下一阶段。

主要内容：

- 新增确定性事件回测引擎，执行 T+1、披露/生成时间检查、持有期、交易成本、滑点和研究性做空约束。
- 输出策略/基准净值、超额收益、年化收益、波动率、夏普、最大回撤、胜率、换手、暴露和逐笔交易。
- 相同输入与方法版本生成稳定运行编号，便于复算；量化 API 需要身份且不持久化数据。
- 前端增加“量化实验”导航，提供受控演示、参数配置、净值曲线、风险指标、交易审计和方法限制。
- 独立人类金标继续评估语义正确性，量化回测评估冻结信号的历史表现，两条评测线分离，避免把回测收益当成模型准确率。

### 阶段 25：独立金标冻结与产品质量中心

状态：最终硬金标已完成冻结；Graph RAG 放量仍由系统基准门禁阻断。

主要内容：

- 两份专业复核后的回收工作簿均通过固定字段、必填项、枚举、证据和时间格式校验，原始文件以 SHA-256 纳入质量报告。
- 新增 `gold_annotation_v3 consensus` 流水线，只冻结 A/B 核心标签完全一致、双方置信度不低于 3 且均无数据问题的样本，不用某一位标注者静默覆盖另一位。
- 360 个任务判断单元中，199 个由双人核心标签共识直接形成金标；其余 161 个均已由独立裁决员完成裁决，最终数据集冻结在 `analytics/datasets/final-gold-v3-20260826`。
- 最终事件语义 120 条、正文事实 60 条、Graph RAG 相关性 180 条；其中 358 条可进入系统评测，`G3-E061` 与 `G3-B053` 因原文不可提取等源数据问题仅保留审计。
- 字段级一致率与 Cohen's kappa 被结构化记录；事件方向 κ=0.8188，正文事实变化方向 κ=0.4880，Graph RAG 相关性 κ=0.5154。
- 新增只读 `/api/evaluation/gold-quality`：身份必需，报告缺失、损坏或版本不匹配时明确返回 503，不伪造通过结果。
- 前端新增“质量中心”，统一展示共识覆盖、困难集、一致性与发布门禁，并明确区分“可离线评测”“最终金标就绪”“Graph RAG 可放量”三个状态。
- 当前 Graph RAG 保持默认关闭：最终相关性金标已可用于下一步系统基准，但 Recall@K、MRR 与权限泄漏门禁尚未产出，不能仅凭人工标签就开启流量。

验证结果：质量 API 单测、共识冻结回归、前端 TypeScript 构建和 ESLint 通过；浏览器实际检查桌面与 520px 窄屏均无横向溢出。

### 阶段 26：最终裁决接入与完整前端呈现

状态：完成。

主要内容：

- 最终金标质量报告升级为 v2，逐任务记录共识数、裁决数、最终数和评测可用数，并对裁决枚举、跨字段约束、裁决时间和原始文件哈希执行冻结校验。
- `/api/evaluation/gold-quality` 与前端质量中心读取最终版本；工作台和复核页同步展示“最终金标 READY / Graph RAG 系统基准待完成”，避免把数据就绪误报为功能已放量。
- 前端七个一级入口均提供完整受控场景：工作台、变化雷达、投资逻辑、复核与复盘、资产治理、质量中心和量化实验；证据详情显示文本链路、关系图链路、融合得分、分层路径及快照版本。
- 受控 Mock 支持新建证券/逻辑、上传处理、证据确认与解除、资料复核、失败重放、逻辑复核、指标映射、发布和版本修订等交互状态；未知路由返回显式 404 页面。
- 移动端导航已覆盖全部七个入口，页面保留人工决策边界、AI 候选标识、原文定位和技术追踪降级提示。

### 阶段 27：Graph RAG 最终金标系统基准与全栈贯通

状态：基准与全栈贯通完成；系统效果门禁 12 项通过 10 项，Graph RAG 继续默认关闭。

主要内容：

- 新增 `graph-rag-final-gold-v1`，在 180 个关系判断、27 个查询上同时评测文本基线与生产
  `GraphRetriever`，记录集合 Recall@1/3/5/10、Hit@K、MRR、NDCG@K 和 Top-1 正确率。
- 基准建图只使用查询、候选原文和冻结概念词表；金标标签仅用于排序后计分，避免评测标签泄漏。
- 每个查询注入跨证券、机密权限和未来时间三类高相似诱饵，共 81 条；返回、路径、引用和
  metadata 的泄漏数均为 0，相关命中的 locator 路径完整率为 100%。
- Graph RAG Recall@5 从文本的 0.7399 提升至 0.7832，MRR 从 0.8333 提升至 0.8367，
  NDCG@5 从 0.7804 提升至 0.8088；Recall@5 未达到 0.80，Top-1 0.6667 未达到 0.70。
- 质量报告、质量 API 和前端质量中心同步展示实测结果与未通过门禁，不把零泄漏或局部提升
  误报为可放量。
- Docker 本地环境完成 `0012_evidence_retrieval_trace` 迁移，PostgreSQL/pgvector、Redis、
  MinIO、API、Worker 与前端 readiness 全部通过；真实数据页面和实际 Graph Snapshot 查询完成验收。
