# 隔离答辩演示环境

该编排用于把本地调试库恢复到与共享 `copilot_dev` 完全不同的数据面：

- Compose 项目：`copilot-demo`
- PostgreSQL：`copilot_demo`，独立 named volume
- Redis：独立 named volume
- MinIO：独立 named volume 和 `copilot-demo-documents` bucket
- 外部入口：`https://demo.47.238.244.65.sslip.io`

只有 API 和 Web 加入已有的 `copilot-integration_app` 入口网络；PostgreSQL、Redis 和 MinIO
只存在于 `copilot-demo_data` 内部网络。共享 `copilot_dev` 及其对象 bucket 不参与恢复。

恢复顺序必须是：创建成套备份、校验 SHA-256、启动空 PostgreSQL/MinIO、恢复数据库及对象
版本、执行 `alembic upgrade head`、创建临时演示账号、启动应用，最后再将 `Caddyfile.site`
加入共享网关。禁止把本文件改造成直接覆盖共享数据库的脚本。
