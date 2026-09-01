.PHONY: help install hooks fmt lint lint-arch lint-contracts lint-assets openapi type test test-integration check migrate revision seed asset-inventory backfill-assets backfill-source-archives backfill-title-fulltext rebuild-search build-embeddings evaluate-p1 backup restore-drill clean
.DEFAULT_GOAL := help

PY := python3

help:
	@echo "install           安装开发依赖"
	@echo "hooks             安装 pre-commit hook（提交前自动跑 check）"
	@echo "fmt               自动修复格式"
	@echo "lint              ruff 检查"
	@echo "lint-arch         分层依赖契约检查"
	@echo "lint-contracts    contracts/ 下 Schema 合法性检查 + OpenAPI 契约未漂移"
	@echo "lint-assets       受控数据资产 SHA-256 与保留策略检查"
	@echo "openapi           由 app/api 重新导出 contracts/api/openapi.yaml"
	@echo "type              mypy 类型检查"
	@echo "test              单元 + 契约测试（不需要数据库）"
	@echo "test-integration  集成测试（需要数据库）"
	@echo "check             提交前门禁，等价于 CI"
	@echo "migrate           应用数据库迁移"
	@echo "revision m=...    生成迁移"
	@echo "seed              导入样例包到本地库"
	@echo "asset-inventory   盘点历史文档、修订、运行与授权状态"
	@echo "backfill-assets    追加历史正文的语义切片、事实与事件运行"
	@echo "backfill-source-archives  只追加回填历史原件、授权核验与归档运行"
	@echo "backfill-title-fulltext  将获授权标题索引原件解析为完整正文并关联当前投资逻辑"
	@echo "rebuild-search    从事实表重建权限感知的切片索引"
	@echo "build-embeddings  按模型版本增量生成 pgvector embedding"
	@echo "evaluate-p1       运行独立金标基线与 RAG 离线评测"
	@echo "backup            创建 PostgreSQL 与对象内容校验备份"
	@echo "restore-drill      在隔离容器完成备份恢复与哈希抽检"

install:
	$(PY) -m pip install -r requirements-dev.txt

# 用 core.hooksPath 而不是拷进 .git/hooks，这样 hook 本身受版本控制，
# 改了对所有人生效，不需要每人重装。
hooks:
	git config core.hooksPath scripts/hooks
	chmod +x scripts/hooks/*
	@echo "已启用。跳过单次检查：git commit --no-verify"

fmt:
	ruff check --fix app analytics scripts tests alembic
	ruff format app analytics scripts tests alembic

lint:
	ruff check app analytics scripts tests alembic
	ruff format --check app analytics scripts tests alembic

lint-arch:
	lint-imports

lint-contracts:
	$(PY) -m scripts.check_contracts
	$(PY) -m scripts.export_openapi --check

lint-assets:
	$(PY) -m scripts.check_governed_assets --check

openapi:
	$(PY) -m scripts.export_openapi

type:
	mypy app

test:
	pytest tests/unit tests/contract -q

test-integration:
	pytest tests/integration -q

# 与 CI 的三个 job 一致：lint / arch / test
check: lint lint-arch lint-contracts lint-assets type test

migrate:
	alembic upgrade head

revision:
	@test -n "$(m)" || (echo "用法: make revision m=\"变更说明\"" && exit 1)
	alembic revision --autogenerate -m "$(m)"

seed:
	$(PY) -m scripts.seed_sample_pack

asset-inventory:
	$(PY) -m scripts.asset_inventory

backfill-assets:
	$(PY) -m scripts.backfill_asset_derivatives

backfill-source-archives:
	$(PY) -m scripts.backfill_source_archives

backfill-title-fulltext:
	$(PY) -m scripts.backfill_title_index_fulltext

rebuild-search:
	$(PY) -m scripts.rebuild_search_index

build-embeddings:
	$(PY) -m scripts.build_embeddings

evaluate-p1:
	$(PY) -m analytics.evaluation.p1_baseline
	$(PY) -m analytics.evaluation.rag_retrieval_eval

backup:
	powershell -ExecutionPolicy Bypass -File scripts/backup_local.ps1

restore-drill:
	powershell -ExecutionPolicy Bypass -File scripts/restore_drill.ps1

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache
