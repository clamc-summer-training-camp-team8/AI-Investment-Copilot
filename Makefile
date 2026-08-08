.PHONY: help install fmt lint lint-arch lint-contracts type test test-integration check migrate revision seed clean
.DEFAULT_GOAL := help

PY := python3

help:
	@echo "install           安装开发依赖"
	@echo "fmt               自动修复格式"
	@echo "lint              ruff 检查"
	@echo "lint-arch         分层依赖契约检查"
	@echo "lint-contracts    contracts/ 下 Schema 合法性检查"
	@echo "type              mypy 类型检查"
	@echo "test              单元 + 契约测试（不需要数据库）"
	@echo "test-integration  集成测试（需要数据库）"
	@echo "check             提交前门禁，等价于 CI"
	@echo "migrate           应用数据库迁移"
	@echo "revision m=...    生成迁移"
	@echo "seed              导入样例包到本地库"

install:
	$(PY) -m pip install -r requirements-dev.txt

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
