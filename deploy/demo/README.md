# 隔离答辩演示环境

该编排用于把本地调试库恢复到与共享 `copilot_dev` 完全不同的数据面：

- Compose 项目：`copilot-demo`
- PostgreSQL：`copilot_demo`，独立 named volume
- Redis：独立 named volume
- MinIO：独立 named volume；bucket 逻辑名沿用本地的 `copilot-documents`，但数据卷完全隔离
- 外部入口：`https://demo.47.238.244.65.sslip.io`

只有 API 和 Web 加入已有的 `copilot-integration_app` 入口网络；PostgreSQL、Redis 和 MinIO
只存在于 `copilot-demo_data` 内部网络。共享 `copilot_dev` 及其对象 bucket 不参与恢复。

恢复顺序必须是：创建成套备份、校验 SHA-256、启动空 PostgreSQL/MinIO、恢复数据库及对象
版本、执行 `alembic upgrade head`、创建临时演示账号、启动应用，最后再将 `Caddyfile.site`
加入共享网关。禁止把本文件改造成直接覆盖共享数据库的脚本。

## 远端目录与日常操作

线上目录固定为 `/opt/ai-investment-copilot-demo`，密钥只保存在该目录的 `.env.demo`
（权限 `0600`），不得提交到 Git。常用检查命令：

```bash
cd /opt/ai-investment-copilot-demo
docker compose --env-file .env.demo -f deploy/docker-compose.demo.yml ps -a
docker compose --env-file .env.demo -f deploy/docker-compose.demo.yml logs --tail=100 api worker
```

演示数据服务没有主机端口映射。仅 `api` 和 `web` 加入
`copilot-integration_app`，由共享 Caddy 根据域名转发；共享栈的 PostgreSQL、Redis、MinIO
均不在演示恢复链路中。

## 下线与回滚

若只需暂停演示应用且保留数据：

```bash
cd /opt/ai-investment-copilot-demo
docker compose --env-file .env.demo -f deploy/docker-compose.demo.yml stop
```

若入口配置异常，先把
`/opt/ai-investment-copilot/deploy/integration/Caddyfile.pre-demo-20260902T093320Z`
恢复为共享 Caddyfile，执行 `caddy validate` 后再重启网关。不要执行 `docker compose down -v`，
除非已经确认可以删除演示数据库和对象存储卷。
