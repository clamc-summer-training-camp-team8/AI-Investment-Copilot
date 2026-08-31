# 后端产品化联调记录（2026-08-11）

## 范围

本轮在 `feat/mvp-closed-loop` 最新实现之上补齐：

1. PostgreSQL 真实迁移、仓储和 FastAPI 持久化联调。
2. OpenAI-compatible `HttpProvider`，包含密钥、超时、重试和结构化输出。
3. Redis/ARQ 文档任务队列、稳定任务 ID、任务所有者隔离和人工降级。
4. 复核任务仓储、服务与 `/api/reviews` 接口。
5. 本地受信任头与非本地 Bearer JWT 双模式鉴权。
6. 九公司实验的研究员标注导入、双人覆盖校验和金标门槛。

## PostgreSQL 验证

本机使用 PostgreSQL 16.14 Windows x64 便携二进制，绑定 `127.0.0.1:5432`，不安装
系统服务。验证步骤：

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic downgrade base
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m pytest tests\integration\db -q
.\.venv\Scripts\python.exe -m pytest tests\integration\test_api_postgres.py -q
```

迁移建立 19 张业务表；降级后只保留 Alembic 自身版本表，再次升级恢复全部结构。
API 联调用例真实写入并读取 `thesis`、`hypothesis`、`review_task` 和 `audit_log`，最后清理
测试记录。

## 模型端点配置

```dotenv
LLM_PROVIDER=http
LLM_ENDPOINT=https://api.deepseek.com/chat/completions
LLM_API_KEY=由密钥管理系统注入
LLM_MODEL_VERSION=deepseek-v4-flash
LLM_TIMEOUT_SECONDS=30
LLM_MAX_RETRIES=2
LLM_MAX_OUTPUT_TOKENS=4096
LLM_THINKING_MODE=disabled
LLM_REASONING_EFFORT=low
```

没有端点和密钥时使用 `LLM_PROVIDER=local`，产品仍可运行确定性规则闭环，但不得将其
效果解释为大模型质量。API Key 只保存在本地 `.env` 或服务端密钥管理系统中。

## 鉴权配置

本地开发：

```dotenv
ENV=local
AUTH_MODE=trusted_headers
```

试点/生产：

```dotenv
ENV=pilot
AUTH_MODE=jwt
AUTH_JWT_SECRET=至少32字节且由密钥管理系统注入
AUTH_JWT_ISSUER=ai-investment-copilot
AUTH_JWT_AUDIENCE=ai-investment-copilot-api
```

系统只验证令牌，不在 MVP 内保存用户密码或签发生产令牌；令牌应由机构身份系统签发。

## 尚需目标环境验证

- 当前 Windows 主机没有 Docker 或原生 Redis，因此 ARQ 通过单元/API mock 验证；部署时仍须
  在 `deploy/docker-compose.local.yml` 或目标 Redis 上完成一次真实入队、消费和重试演练。
- 尚未在本机 `.env` 注入 DeepSeek API Key；完成后须在 `researcher-gold-v1` 上记录真实模型
  的契约通过率、方向指标、延迟和 token 费用。
- 本机 Python 为 3.12，项目声明为 Python >=3.13；合并前必须在 3.13 CI 重放。
