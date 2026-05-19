.DEFAULT_GOAL := help

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[32mmake %-12s\033[0m %s\n", $$1, $$2}'

install: ## Install project + cli + dev deps into a uv-managed venv
	uv sync --extra cli --extra dev

lint: ## Run ruff lint
	uv run ruff check .

fix: ## Auto-fix ruff lint issues
	uv run ruff check --fix .

format: ## Format all files with ruff
	uv run ruff format .

format-check: ## Check formatting without modifying files
	uv run ruff format --check .

typecheck: ## Run pyright in strict mode
	uv run pyright

test: ## Run the test suite
	uv run pytest

check: lint format-check typecheck test ## Run every check CI runs

precommit: ## Install pre-commit hooks
	uv run pre-commit install

clean: ## Remove caches and build artifacts
	rm -rf .ruff_cache .pytest_cache .pyright build dist *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

.PHONY: help install lint fix format format-check typecheck test check precommit clean
