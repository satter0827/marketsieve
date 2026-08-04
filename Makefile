SHELL := /bin/sh
.DEFAULT_GOAL := help

STATE_DIR ?= .marketsieve
TEST ?=
BASE_SHA ?= origin/develop
HEAD_SHA ?= HEAD
HEAD_COMMIT = $(shell git rev-parse $(HEAD_SHA))
EVIDENCE_DIR ?= $(STATE_DIR)/artifacts/checks/$(HEAD_COMMIT)
REVIEW_DIR ?= $(STATE_DIR)/artifacts/review/$(HEAD_COMMIT)
BUNDLE ?= $(REVIEW_DIR)
VERSION ?=
COMMIT ?=
RELEASE_DIR ?= $(STATE_DIR)/artifacts/release/$(COMMIT)

export UV_CACHE_DIR := $(abspath $(STATE_DIR))/cache/uv
export PYTHONPYCACHEPREFIX := $(abspath $(STATE_DIR))/cache/python

.PHONY: help sync format format-check lint typecheck test check doctor demo demo-json build review review-bundle review-validate release-build release-verify release-check clean-generated

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
	EVIDENCE_DIR="$(EVIDENCE_DIR)" uv run python scripts/develop_gate.py check all

doctor: ## Run offline installation diagnostics.
	uv run marketsieve doctor

demo: ## Run the deterministic JP and US offline demo as text.
	uv run marketsieve demo --market all --format text

demo-json: ## Run the deterministic JP and US offline demo as JSON.
	uv run marketsieve demo --market all --format json

build: ## Build the public SDK into the generated-artifact directory.
	@mkdir -p "$(STATE_DIR)/artifacts/build"
	uv build --package marketsieve --out-dir "$(STATE_DIR)/artifacts/build"

review: check review-bundle ## Run the development gate and create a review bundle.

review-bundle: ## Create a review bundle from existing development evidence.
	uv run python scripts/review_gate.py create --base-sha "$(BASE_SHA)" --head-sha "$(HEAD_SHA)" --evidence-dir "$(EVIDENCE_DIR)" --output-dir "$(REVIEW_DIR)"

review-validate: ## Validate BUNDLE=<review-bundle-directory>.
	@test -n "$(BUNDLE)" || { echo "BUNDLE is required" >&2; exit 2; }
	uv run python scripts/review_gate.py validate "$(BUNDLE)"

release-build: ## Build VERSION at COMMIT once into the release directory.
	@test -n "$(VERSION)" && test -n "$(COMMIT)" || { echo "VERSION and COMMIT are required" >&2; exit 2; }
	uv run python scripts/release_gate.py build --version "$(VERSION)" --commit "$(COMMIT)" --dist-dir "$(RELEASE_DIR)"

release-verify: ## Verify an existing VERSION and COMMIT release directory.
	@test -n "$(VERSION)" && test -n "$(COMMIT)" || { echo "VERSION and COMMIT are required" >&2; exit 2; }
	python3 scripts/release_gate.py verify --version "$(VERSION)" --commit "$(COMMIT)" --dist-dir "$(RELEASE_DIR)"

release-check: release-build release-verify ## Build once and verify a release candidate locally.

clean-generated: ## Remove only the repository-local generated-state directory.
	@test "$(STATE_DIR)" = ".marketsieve" || { echo "STATE_DIR must be .marketsieve" >&2; exit 2; }
	rm -rf -- .marketsieve
