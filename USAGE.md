# AI Investment Copilot 使用手册

本文说明如何在本地启动当前 MVP 后端、连接前端、调用核心 API，以及复算三行业九公司
验证结果。项目约束、模块边界与协作规范仍以根目录 [README.md](README.md) 为准。

## 1. 当前可运行范围

当前仓库已经具备：

- FastAPI 后端与 OpenAPI 契约；
- PostgreSQL 持久化与 Alembic 迁移；
- Redis + ARQ 文档处理后台任务；
- 本地受信请求头和生产 JWT 两种鉴权模式；
- OpenAI-compatible Chat Completions 模型提供者，当前已按 DeepSeek V4 Flash 配置；
- 投资逻辑草稿、人工发布、证据处置、状态建议、复核中心与审计接口；
- 半导体、医药、新能源汽车共九家公司的公开数据与离线验证产物。

系统只生成 AI 草稿、候选证据和状态建议，不生成交易、评级或调仓指令。AI 结果必须经过
研究员确认后才能进入正式记录。

## 2. 环境要求

- Git
- Python 3.13（以 `pyproject.toml` 为准）
- Docker Desktop 或兼容的 Docker Compose
- PostgreSQL 16 与 Redis 7 由 Compose 自动启动
- 可选：GNU Make。Windows 没有 Make 也可以直接运行本文给出的 Python 命令

以下命令默认在仓库根目录执行。

## 3. 首次安装

### Windows PowerShell

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

如果 PowerShell 禁止执行激活脚本，可以不激活环境，后续把 `python` 替换为
`.\.venv\Scripts\python.exe`。

### macOS / Linux

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
cp .env.example .env
```

`.env` 已被 Git 忽略。不要把 API Key、JWT 密钥或数据库生产凭据写进任何受版本控制的
文件。

## 4. 配置模型提供者

### 4.1 不调用外部模型

适合离线开发、接口联调和 CI。在 `.env` 中设置：

```dotenv
LLM_PROVIDER=local
LLM_MODEL_VERSION=local-rule-v1
LLM_API_KEY=
```

### 4.2 使用 DeepSeek V4 Flash

当前实现使用 OpenAI-compatible Chat Completions，不使用 Responses API：

```dotenv
LLM_PROVIDER=http
LLM_ENDPOINT=https://api.deepseek.com/chat/completions
LLM_API_KEY=<只填写在本机 .env 中的密钥>
LLM_MODEL_VERSION=deepseek-v4-flash
LLM_THINKING_MODE=disabled
```

服务端只保存结构化结果与模型版本，不保存 API Key、完整提示词或供应商原始响应。启动
API 或 worker 前修改 `.env`；Pydantic Settings 会在进程启动时读取配置。

## 5. 启动完整后端

完整产品链路需要三个进程：PostgreSQL/Redis、FastAPI、ARQ worker。

### 5.1 启动基础设施

```powershell
docker compose -f deploy/docker-compose.local.yml up -d
docker compose -f deploy/docker-compose.local.yml ps
```

默认只监听本机：

- PostgreSQL：`127.0.0.1:5432`
- Redis：`127.0.0.1:6379`

### 5.2 初始化数据库

```powershell
python -m alembic upgrade head
python -m scripts.seed_sample_pack
```

`seed_sample_pack` 导入的是带 `is_illustrative=true` 的虚构演示数据，只用于本地联调。
`real_data/` 中的九家公司公开数据属于离线评测数据，不会由这个命令自动写入产品库。

如果只想检查样例包而不写数据库：

```powershell
python -m scripts.seed_sample_pack --dry-run
```

### 5.3 启动 API

在第一个终端运行：

```powershell
python -m uvicorn app.api.main:app --reload --host 127.0.0.1 --port 8000
```

常用地址：

- 存活检查：<http://127.0.0.1:8000/health>
- PostgreSQL + Redis 就绪检查：<http://127.0.0.1:8000/health/ready>
- Swagger UI：<http://127.0.0.1:8000/docs>
- OpenAPI JSON：<http://127.0.0.1:8000/openapi.json>

PowerShell 验证：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

`/health` 返回成功只代表 API 进程存活；产品联调应以 `/health/ready` 返回 200 为准。

### 5.4 启动后台 worker

在第二个终端激活同一虚拟环境后运行：

```powershell
arq app.workers.settings.WorkerSettings
```

worker 负责 PDF、DOCX、TXT 的解析、切片、AI 草稿生成与失败重试。未启动 worker 时，
上传接口仍可能返回任务 ID，但任务不会被消费。

## 6. 本地鉴权与 API 调用

### 6.1 本地开发模式

`.env.example` 默认使用：

```dotenv
ENV=local
AUTH_MODE=trusted_headers
```

业务接口必须提供 ASCII 用户 ID。PowerShell 示例：

```powershell
$headers = @{
  "X-User-Id" = "researcher-a"
  "X-User-Teams" = "team-8"
}

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/api/workbench" `
  -Headers $headers

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/api/theses?limit=20&offset=0" `
  -Headers $headers
```

不要在 HTTP 头中传中文姓名。账号 ID 放请求头，中文展示名由产品数据负责。

### 6.2 JWT 模式

试点和生产必须配置：

```dotenv
ENV=pilot
AUTH_MODE=jwt
AUTH_JWT_SECRET=<至少 32 字节的强随机密钥>
AUTH_JWT_ISSUER=ai-investment-copilot
AUTH_JWT_AUDIENCE=ai-investment-copilot-api
```

客户端使用 `Authorization: Bearer <token>`。令牌必须包含有效的 `sub`、`iat`、`exp`、
`iss` 和 `aud`。非本地环境会拒绝 `trusted_headers` 模式。

## 7. 典型产品流程

推荐先通过 Swagger UI 联调。完整字段和响应以
[OpenAPI 契约](contracts/api/openapi.yaml) 为唯一事实来源。

### 7.1 从观点创建 AI 草稿

`POST /api/theses/drafts`

```json
{
  "security_id": "600276",
  "view": "创新药获批和商业化放量可能推动未来收入增长"
}
```

返回的是候选草稿，不会自动发布。研究员补充方向、期限和复核日后，再调用
`POST /api/theses/{thesis_id}/publish` 完成人工发布。

### 7.2 上传文档进入后台任务

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/jobs/documents" `
  -H "X-User-Id: researcher-a" `
  -H "X-User-Teams: team-8" `
  -F "file=@C:\path\to\report.pdf" `
  -F "published_at=2026-08-11T09:00:00+08:00"
```

接口返回 `job_id` 后查询：

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/api/jobs/<job_id>" `
  -Headers $headers
```

注意：

- 只支持 PDF、DOCX、TXT；
- `published_at` 如果提供，必须带时区；
- 需要基于文档生成指定逻辑的 AI 草稿时，`thesis_id` 和 `security_id` 必须同时提供；
- 默认上传上限为 20 MiB，可通过 `UPLOAD_MAX_BYTES` 调整。

### 7.3 人工闸门

以下动作都必须由研究员显式提交：

- 发布 AI 草稿；
- 确认、驳回、修改关联或暂不判断候选证据；
- 接受、拒绝或修改状态建议，并填写原因；
- 完成复核任务并填写裁决结果。

后端不会让 worker 或模型直接把候选内容推进为正式结论。

## 8. 前端联调

前端以 [contracts/api/openapi.yaml](contracts/api/openapi.yaml) 生成类型或 mock，不应从
后端源码推断字段。当前后端注册 19 条路径，覆盖工作台、逻辑卡片、证据、状态建议、
复核中心、文档任务以及健康检查。

本地前端默认允许来源为 `http://localhost:5173`。如果前端使用其他端口，在 `.env`
修改 JSON 数组：

```dotenv
CORS_ORIGINS=["http://localhost:5173","http://127.0.0.1:5173"]
```

接口发生变化后重新生成并检查契约：

```powershell
python -m scripts.export_openapi
python -m scripts.export_openapi --check
```

## 9. 复算三行业九公司 MVP

这些命令使用仓库中的公开数据，属于离线分析，不要求启动 FastAPI、PostgreSQL 或
Redis。

### 9.1 九公司基本面闭环

```powershell
python -m analytics.pipelines.mvp_closure
```

输出目录：

`analytics/experiments/20260811-cn-nine-mvp-closure/`

主要结果包括 `REPORT.md`、`results.json`、`event_results.csv` 和复核队列。默认命令会
重写这些正式产物；只是调试时建议通过 `--output storage/mvp-closure-smoke` 写入 Git
忽略目录。

### 9.2 DeepSeek 单条冒烟与 27 事件评测

单条冒烟应写入临时目录，避免覆盖已经冻结的正式报告：

```powershell
python -m analytics.evaluation.run_nine_company_model `
  --limit 1 `
  --json-output storage/deepseek-smoke/results.json `
  --report-output storage/deepseek-smoke/report.md
```

确认端点、密钥和结构化输出正常后，才运行全部 27 个事件：

```powershell
python -m analytics.evaluation.run_nine_company_model
```

完整运行会调用外部模型并覆盖实验目录中的正式 DeepSeek 结果，应先确认额度、模型版本
和是否确实要重跑。

### 9.3 独立盲标分析与规则评测

```powershell
python -m analytics.evaluation.blind_gold_analysis
python -m analytics.evaluation.run_evaluation
python -m analytics.experiments.run_signal_experiment
```

关键报告：

- `real_data/dataset/blind_annotation_result/REPORT.md`
- `real_data/reports/evaluation_report.md`
- `analytics/experiments/20260811-三行业事件方向信号/result.md`

当前结果只能支持“流程可复算、筛选能力有一定价值、方向判断仍需人工复核”，不能表述为
“AI 已证明能够稳定创造 Alpha”。

## 10. 测试与提交前检查

有 Make 时：

```powershell
make check
make test-integration
```

Windows 无 Make 时：

```powershell
python -m ruff check app analytics scripts tests
python -m ruff format --check app analytics scripts tests
lint-imports
python -m scripts.check_contracts
python -m scripts.export_openapi --check
python -m mypy app
python -m pytest tests/unit tests/contract -q
python -m pytest tests/integration -q
```

需要一次性运行全部测试时：

```powershell
python -m pytest
```

## 11. 停止服务与数据保留

停止容器但保留 PostgreSQL 和 Redis 数据卷：

```powershell
docker compose -f deploy/docker-compose.local.yml down
```

不要随意添加 `-v`；它会删除本地数据库和 Redis 数据卷。只有明确要重建所有本地数据
时才使用该选项。

## 12. 常见问题

### `/health` 正常但 `/health/ready` 返回 503

检查容器状态、`.env` 中的 `DATABASE_URL`/`REDIS_URL`，并确认已执行迁移：

```powershell
docker compose -f deploy/docker-compose.local.yml ps
python -m alembic current
```

### 上传任务一直处于 queued

确认 Redis 正常且 ARQ worker 已在另一个终端运行。API 和 worker 必须读取同一个
`REDIS_URL`。

### AI 接口返回 503

检查 `LLM_PROVIDER`、`LLM_ENDPOINT`、模型名与 API Key；先使用写入 `storage/` 的单条
冒烟命令定位问题。不要把密钥或完整请求体贴到 Issue、日志或聊天记录中。

### 本地接口返回 401

`trusted_headers` 模式要传 `X-User-Id`；JWT 模式要传有效 Bearer token。只有 `/health`
与 `/health/ready` 不要求业务身份。

### 无权查看对象时返回 404

这是预期行为。系统刻意不区分“对象不存在”和“对象存在但无权限”，防止通过枚举 ID
推断其他研究员的覆盖范围。

### OpenAPI 检查失败

后端路由变更后运行：

```powershell
python -m scripts.export_openapi
```

确认契约变更符合预期，再将代码与 `contracts/api/openapi.yaml` 一起提交。

## 13. 延伸文档

- [项目概览与模块地图](README.md)
- [本地和试点部署说明](deploy/README.md)
- [API 契约说明](contracts/api/README.md)
- [后台任务说明](app/workers/README.md)
- [离线分析规范](analytics/README.md)
- [三行业九公司验收报告](docs/data/MVP验收报告-三行业九公司.md)
- [远端接入手册](docs/collaboration/远端接入手册.md)
