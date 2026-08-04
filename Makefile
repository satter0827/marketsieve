SHELL := /bin/sh
.DEFAULT_GOAL := help

STATE_DIR ?= .marketsieve
TEST ?=

export UV_CACHE_DIR := $(abspath $(STATE_DIR))/cache/uv
export PYTHONPYCACHEPREFIX := $(abspath $(STATE_DIR))/cache/python

.PHONY: help sync format format-check lint typecheck test check doctor build clean-generated

help: ## Show the available project commands.
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "%-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

sync: ## Install the locked workspace and development dependencies.
	uv sync --locked

format: ## Format source, tests, scripts, and configuration snippets.
	uv run ruff format .

format-check: ## Check formatting without changing files.
	uv run ruff format --check .

lint: ## Run Ruff lint checks.
	uv run ruff check .

typecheck: ## Run strict static type checks.
	uv run mypy

test: ## Run all tests, or TEST=<path> for a focused test.
	uv run pytest $(TEST)

check: ## Run the complete development gate.
	uv run python scripts/quality_gate.py check all

doctor: ## Run offline installation diagnostics.
	uv run marketsieve doctor

build: ## Build the public SDK into the generated-artifact directory.
	@mkdir -p "$(STATE_DIR)/artifacts/build"
	uv build --package marketsieve --out-dir "$(STATE_DIR)/artifacts/build"

clean-generated: ## Remove only the repository-local generated-state directory.
	@test "$(STATE_DIR)" = ".marketsieve" || { echo "STATE_DIR must be .marketsieve" >&2; exit 2; }
	rm -rf -- .marketsieve
