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