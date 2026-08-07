SHELL := /bin/sh
.DEFAULT_GOAL := help

STATE_DIR ?= .marketsieve
TEST ?=
CONFIG ?= marketsieve.toml
PORTFOLIO ?=
BROKER ?= canonical
INSTRUMENT ?=
AS_OF ?= $(shell date +"%Y-%m-%dT%H:%M:%S%z")
BASE_SHA ?= origin/develop
HEAD_SHA ?= HEAD
REVIEWED_SHA ?=
HEAD_COMMIT = $(shell git rev-parse $(HEAD_SHA))
EVIDENCE_DIR ?= $(STATE_DIR)/artifacts/checks/$(HEAD_COMMIT)
REVIEW_DIR ?= $(STATE_DIR)/artifacts/review/$(HEAD_COMMIT)
BUNDLE ?= $(REVIEW_DIR)
VERSION ?=
COMMIT ?=
RELEASE_DIR ?= $(STATE_DIR)/artifacts/release/$(COMMIT)
CONFIGURATION_PYTHON ?= .venv/bin/python

export UV_CACHE_DIR := $(abspath $(STATE_DIR))/cache/uv
export PYTHONPYCACHEPREFIX := $(abspath $(STATE_DIR))/cache/python

.PHONY: help setup-config portfolio-import portfolio-show daily-status market-matrix watchlist-add watchlist-remove watchlist-show daily-jp daily-us weekly doctor sync format format-check lint typecheck test secret-check check capabilities-json build evidence evidence-bundle evidence-validate review-attest governance-check release-build release-verify release-check

help: ## Show daily-use commands first, followed by developer commands.
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "%-22s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup-config: ## First use: create the non-secret configuration without overwriting an existing file.
	@if test -f "$(CONFIG)"; then \
		echo "Configuration already exists: $(CONFIG)"; \
	else \
		cp marketsieve.example.toml "$(CONFIG)"; \
		echo "Created configuration: $(CONFIG)"; \
	fi
	@echo "Credentials stay in environment variables and are never written to this file."
	@echo "Next VS Code operation: 02 First Run: Import Portfolio CSV"

portfolio-import: ## First use: import PORTFOLIO=... with BROKER=canonical|rakuten (Offline).
	@test -n "$(PORTFOLIO)" || { echo "PORTFOLIO is required. Next: make portfolio-import PORTFOLIO=/absolute/path/holdings.csv" >&2; exit 2; }
	@test -f "$(PORTFOLIO)" || { echo "Portfolio file not found: $(PORTFOLIO)" >&2; exit 2; }
	uv run marketsieve portfolio import "$(PORTFOLIO)" --broker "$(BROKER)" --as-of "$(AS_OF)"
	@echo "Imported with as-of: $(AS_OF)"
	@echo "Next VS Code operation: 03 First Run: Check Readiness"

portfolio-show: ## Show the latest normalized portfolio (Offline).
	uv run marketsieve portfolio show

daily-status: ## Check configuration, portfolio, reports, and installation (Offline).
	@if ! test -f "$(CONFIG)"; then \
		echo "[invalid] configuration: file not found: $(CONFIG)"; \
		exit 2; \
	fi
	@"$(CONFIGURATION_PYTHON)" -m scripts.configuration_check --syntax-only "$(CONFIG)" || { echo "Next: correct $(CONFIG)" >&2; exit 2; }
	@uv run marketsieve doctor
	@uv run python -m scripts.configuration_check "$(CONFIG)" || { echo "Next: correct $(CONFIG) or the credential environment variables" >&2; exit 2; }
	@uv run marketsieve report list --output json
	@uv run python -m scripts.portfolio_check "$(CONFIG)"

market-matrix: ## Build the full yfinance market matrix with no registration or API key.
	@if test -f "$(CONFIG)"; then \
		uv run marketsieve --config "$(CONFIG)" matrix refresh; \
	elif test "$(origin CONFIG)" != "file"; then \
		echo "Configuration file not found: $(CONFIG)" >&2; \
		exit 2; \
	else \
		uv run marketsieve matrix refresh; \
	fi

watchlist-add: ## Add INSTRUMENT=MIC:SYMBOL (Offline).
	@test -n "$(INSTRUMENT)" || { echo "INSTRUMENT is required. Next: make watchlist-add INSTRUMENT=XTKS:7203" >&2; exit 2; }
	uv run marketsieve watchlist add "$(INSTRUMENT)"

watchlist-remove: ## Remove INSTRUMENT=MIC:SYMBOL (Offline).
	@test -n "$(INSTRUMENT)" || { echo "INSTRUMENT is required. Next: make watchlist-remove INSTRUMENT=XTKS:7203" >&2; exit 2; }
	uv run marketsieve watchlist remove "$(INSTRUMENT)"

watchlist-show: ## Show the current watchlist and history IDs (Offline).
	uv run marketsieve watchlist show

daily-jp: ## Analyze JP holdings and watchlist, then store a static report (Network).
	@test -f "$(CONFIG)" || { echo "Missing $(CONFIG). Next VS Code operation: 01 First Run: Create Configuration" >&2; exit 2; }
	uv run marketsieve --config "$(CONFIG)" daily jp

daily-us: ## Analyze US holdings and watchlist, then store a static report (Network).
	@test -f "$(CONFIG)" || { echo "Missing $(CONFIG). Next VS Code operation: 01 First Run: Create Configuration" >&2; exit 2; }
	uv run marketsieve --config "$(CONFIG)" daily us

weekly: ## Build the static weekly brief from eligible JP and US reports (Offline).
	@test -f "$(CONFIG)" || { echo "Missing $(CONFIG). Next VS Code operation: 01 First Run: Create Configuration" >&2; exit 2; }
	uv run marketsieve --config "$(CONFIG)" weekly

doctor: ## Run offline installation diagnostics.
	uv run marketsieve doctor

sync: ## Install the locked workspace and development dependencies.
	uv sync --locked
	uv run python scripts/runtime_wheelhouse.py prepare --output "$(STATE_DIR)/cache/runtime-wheelhouse"

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

secret-check: ## Scan tracked files and the current diff without printing secret values.
	uv run python scripts/secret_gate.py --base "$(BASE_SHA)"

check: ## Run the complete development gate.
	BASE_SHA="$(BASE_SHA)" EVIDENCE_DIR="$(EVIDENCE_DIR)" uv run python -m scripts.develop_gate check all

capabilities-json: ## Describe the CLI machine contract.
	uv run marketsieve capabilities --output json

build: ## Build all public distributions into the generated-artifact directory.
	uv run python -m scripts.package_catalog build --out-dir "$(STATE_DIR)/artifacts/build"

evidence: check evidence-bundle ## Run the development gate and create a review bundle.

evidence-bundle: ## Create a review bundle from existing development evidence.
	uv run python -m scripts.review_gate create --base-sha "$(BASE_SHA)" --head-sha "$(HEAD_SHA)" --evidence-dir "$(EVIDENCE_DIR)" --output-dir "$(REVIEW_DIR)"

evidence-validate: ## Validate BUNDLE=<review-bundle-directory>.
	@test -n "$(BUNDLE)" || { echo "BUNDLE is required" >&2; exit 2; }
	uv run python -m scripts.review_gate validate "$(BUNDLE)"

review-attest: ## Publish the reviewed HEAD status for REVIEWED_SHA=<full-commit-sha>.
	@test -n "$(REVIEWED_SHA)" || { echo "REVIEWED_SHA is required" >&2; exit 2; }
	uv run python -m scripts.review_attestation attest --reviewed-sha "$(REVIEWED_SHA)"

governance-check: ## Compare checked-in rulesets with active GitHub settings.
	uv run python -m scripts.governance_gate verify

release-build: ## Build VERSION at COMMIT once into the release directory.
	@test -n "$(VERSION)" && test -n "$(COMMIT)" || { echo "VERSION and COMMIT are required" >&2; exit 2; }
	uv run python -m scripts.release_gate build --version "$(VERSION)" --commit "$(COMMIT)" --dist-dir "$(RELEASE_DIR)"

release-verify: ## Verify an existing VERSION and COMMIT release directory.
	@test -n "$(VERSION)" && test -n "$(COMMIT)" || { echo "VERSION and COMMIT are required" >&2; exit 2; }
	python3 -m scripts.release_gate verify --version "$(VERSION)" --commit "$(COMMIT)" --dist-dir "$(RELEASE_DIR)"

release-check: release-build release-verify ## Build once and verify a release candidate locally.
