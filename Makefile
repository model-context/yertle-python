.DEFAULT_GOAL := help

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[32mmake %-12s\033[0m %s\n", $$1, $$2}'

install: ## Install project + all runtime extras + dev deps into a uv-managed venv
	# All extras: pyright typechecks src/yertle/{sre,mcp}/ which import
	# langchain / fastmcp. Without --extra sre --extra mcp, pyright can't
	# resolve those imports and CI fails with `reportMissingImports`.
	uv sync --extra cli --extra sre --extra mcp --extra dev

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

# ---------------------------------------------------------------------------
# SRE agent passthroughs (require `uv sync --extra sre`)
# ---------------------------------------------------------------------------
ask: ## Ask the agent a one-shot question (usage: make ask Q="your question")
	@if [ -z "$(strip $(Q))" ]; then \
	  echo 'Usage: make ask Q="your question"' >&2; \
	  echo '       (the Q= prefix is required — make treats unquoted args as targets)' >&2; \
	  exit 2; \
	fi
	@uv run yertle-sre ask "$(Q)"

repl: ## Start the interactive SRE REPL
	uv run yertle-sre repl

status: ## Show auth/connection status for all underlying CLIs (SRE)
	uv run yertle-sre status

precommit: ## Install pre-commit hooks
	uv run pre-commit install

clean: ## Remove caches and build artifacts
	rm -rf .ruff_cache .pytest_cache .pyright build dist *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

.PHONY: help install lint fix format format-check typecheck test check ask repl status precommit clean
