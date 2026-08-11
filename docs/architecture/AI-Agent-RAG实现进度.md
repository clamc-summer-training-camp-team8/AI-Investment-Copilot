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

## 后续阶段占位

### 阶段 2：公告正文采集和文档标准化

目标：从公告 CSV 的详情 URL 获取 HTML/PDF，缓存原文件，生成带 locator 的标准文档和段落。

### 阶段 3：最小 RAG

目标：建立 Retriever 接口，先实现本地持久化向量检索，保留公司、时间、来源和权限过滤。

### 阶段 4：投资逻辑变化 Agent

目标：编排 Thesis 召回、RAG、事件影响分析、确定性计算、引用校验和人工确认。

### 阶段 5：真实数据 Demo 与评测

目标：使用云南白药验证公告 RAG，使用储能案例验证完整投资逻辑变化闭环。
