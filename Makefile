.PHONY: help install hooks fmt lint lint-arch lint-contracts openapi type test test-integration check migrate revision seed clean
.DEFAULT_GOAL := help

PY := python3

help:
	@echo "install           安装开发依赖"
	@echo "hooks             安装 pre-commit hook（提交前自动跑 check）"
	@echo "fmt               自动修复格式"
	@echo "lint              ruff 检查"
	@echo "lint-arch         分层依赖契约检查"
	@echo "lint-contracts    contracts/ 下 Schema 合法性检查 + OpenAPI 契约未漂移"
	@echo "openapi           由 app/api 重新导出 contracts/api/openapi.yaml"
	@echo "type              mypy 类型检查"
	@echo "test              单元 + 契约测试（不需要数据库）"
	@echo "test-integration  集成测试（需要数据库）"
	@echo "check             提交前门禁，等价于 CI"
	@echo "migrate           应用数据库迁移"
	@echo "revision m=...    生成迁移"
	@echo "seed              导入样例包到本地库"

install:
	$(PY) -m pip install -r requirements-dev.txt

# 用 core.hooksPath 而不是拷进 .git/hooks，这样 hook 本身受版本控制，
# 改了对所有人生效，不需要每人重装。
hooks:
	git config core.hooksPath scripts/hooks
	chmod +x scripts/hooks/*
	@echo "已启用。跳过单次检查：git commit --no-verify"

fmt:
	ruff check --fix app analytics scripts tests
	ruff format app analytics scripts tests

lint:
	ruff check app analytics scripts tests
	ruff format --check app analytics scripts tests

lint-arch:
	lint-imports

lint-contracts:
	$(PY) -m scripts.check_contracts
	$(PY) -m scripts.export_openapi --check

openapi:
	$(PY) -m scripts.export_openapi

type:
	mypy app

test:
	pytest tests/unit tests/contract -q

test-integration:
	pytest tests/integration -q

# 与 CI 的三个 job 一致：lint / arch / test
check: lint lint-arch lint-contracts type test

migrate:
	alembic upgrade head

revision:
	@test -n "$(m)" || (echo "用法: make revision m=\"变更说明\"" && exit 1)
	alembic revision --autogenerate -m "$(m)"

seed:
	$(PY) -m scripts.seed_sample_pack

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache
