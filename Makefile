SHELL := /bin/sh
.DEFAULT_GOAL := help

STATE_DIR ?= .marketsieve
TEST ?=
RESPONSE ?=
REPORT ?= latest
CONFIG ?= marketsieve.toml
CONTROLLED ?= 0
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

export UV_CACHE_DIR := $(abspath $(STATE_DIR))/cache/uv
export PYTHONPYCACHEPREFIX := $(abspath $(STATE_DIR))/cache/python

.PHONY: help daily-jp-ai daily-us-ai weekly-ai ai-prepare ai-import ai-show doctor sync format format-check lint typecheck test secret-check check capabilities-json build evidence evidence-bundle evidence-validate review-attest governance-check release-build release-verify release-check clean-generated

help: ## Show daily-use commands first, followed by developer commands.
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "%-22s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

daily-jp-ai: ## Daily JP close report (Network), then prepare a ChatGPT request.
	@test -f "$(CONFIG)" || { echo "Missing $(CONFIG). Next: cp marketsieve.example.toml $(CONFIG), edit it, then run make doctor" >&2; exit 2; }
	uv run marketsieve --config "$(CONFIG)" daily jp
	uv run marketsieve ai prepare report latest

daily-us-ai: ## Daily US close report (Network), then prepare a ChatGPT request.
	@test -f "$(CONFIG)" || { echo "Missing $(CONFIG). Next: cp marketsieve.example.toml $(CONFIG), edit it, then run make doctor" >&2; exit 2; }
	uv run marketsieve --config "$(CONFIG)" daily us
	uv run marketsieve ai prepare report latest

weekly-ai: ## Weekly brief (Offline), then prepare a ChatGPT request.
	@test -f "$(CONFIG)" || { echo "Missing $(CONFIG). Next: cp marketsieve.example.toml $(CONFIG), edit it, then run make doctor" >&2; exit 2; }
	uv run marketsieve --config "$(CONFIG)" weekly
	uv run marketsieve ai prepare report latest

ai-prepare: ## Prepare ChatGPT request from REPORT=latest (Offline).
	uv run marketsieve ai prepare report "$(REPORT)"

ai-import: ## Import RESPONSE=... (Offline); add CONTROLLED=1 only after checking chat conditions.
	@test -n "$(RESPONSE)" || { echo "RESPONSE is required. Next: make ai-import RESPONSE=/absolute/path/response.json" >&2; exit 2; }
	@test -f "$(RESPONSE)" || { echo "Response file not found: $(RESPONSE)" >&2; exit 2; }
	uv run marketsieve ai import "$(RESPONSE)" $(if $(filter 1,$(CONTROLLED)),--controlled,)

ai-show: ## Show the latest validated AI explanation (Offline).
	uv run marketsieve ai show latest

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

clean-generated: ## Remove only the repository-local generated-state directory.
	@test "$(STATE_DIR)" = ".marketsieve" || { echo "STATE_DIR must be .marketsieve" >&2; exit 2; }
	rm -rf -- .marketsieve
