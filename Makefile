SHELL := /bin/sh
.DEFAULT_GOAL := help

STATE_DIR ?= .marketsieve
GATE_JOBS ?= 0
TEST ?=
SETTINGS ?= marketsieve.settings.toml
SCOPE ?= --all
EVIDENCE ?= --evidence price --evidence company --evidence financials --evidence benchmarks
HISTORY_DAYS ?= 1095
SNAPSHOT ?= latest
INSTRUMENT ?=
INSTRUMENTS ?=
RESEARCH_EVIDENCE ?= --evidence price --evidence company --evidence financials --evidence events --evidence benchmarks
RESEARCH_HISTORY_DAYS ?= 3653
RESEARCH_ID ?= latest
MARKET ?= jp
SESSION ?= close
PORT ?= 0
AS_OF ?=
RUN_ID ?=
LEFT_SNAPSHOT ?=
RIGHT_SNAPSHOT ?=
BASE_SHA ?= origin/develop
HEAD_SHA ?= HEAD
REVIEWED_SHA ?=
PREVIOUS_REVIEWED_SHA ?=
HEAD_COMMIT = $(shell git rev-parse $(HEAD_SHA))
EVIDENCE_DIR ?= $(STATE_DIR)/artifacts/checks/$(HEAD_COMMIT)
REVIEW_DIR ?= $(STATE_DIR)/artifacts/review/$(HEAD_COMMIT)
BUNDLE ?= $(REVIEW_DIR)
VERSION ?=
COMMIT ?=
RELEASE_DIR ?= $(STATE_DIR)/artifacts/release/$(COMMIT)

export UV_CACHE_DIR := $(abspath $(STATE_DIR))/cache/uv
export PYTHONPYCACHEPREFIX := $(abspath $(STATE_DIR))/cache/python

.PHONY: help setup-settings doctor artifacts-doctor artifacts-list run-list market-build market-capture market-reconstruct market-resume market-list market-show market-preview market-query market-security market-compare market-diff research-build research-list research-show research-preview sync format format-check lint typecheck test secret-check check capabilities-json build evidence evidence-bundle evidence-validate review-attest governance-check release-build release-verify release-check

help: ## Show operational and developer commands.
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "%-22s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup-settings: ## Create optional runtime settings without overwriting an existing file.
	@if test -f "$(SETTINGS)"; then echo "Settings already exist: $(SETTINGS)"; else cp marketsieve.settings.example.toml "$(SETTINGS)"; echo "Created settings: $(SETTINGS)"; fi

doctor: ## Check the local runtime and installed packages.
	uv run marketsieve doctor

artifacts-doctor: ## Classify current, legacy, damaged, and orphan artifacts.
	uv run marketsieve artifacts doctor --output json

artifacts-list: ## List artifact inventory as stable JSON.
	uv run marketsieve artifacts list --output json

run-list: ## List structured generation runs.
	uv run marketsieve run list --output json

market-build: ## Build a Snapshot; override SCOPE, EVIDENCE, and HISTORY_DAYS.
	@if test -f "$(SETTINGS)"; then uv run marketsieve --settings "$(SETTINGS)" market build $(SCOPE) $(EVIDENCE) --history-days "$(HISTORY_DAYS)" --output json; else uv run marketsieve market build $(SCOPE) $(EVIDENCE) --history-days "$(HISTORY_DAYS)" --output json; fi

market-capture: ## Capture MARKET=jp|us after the selected close SESSION.
	@if test -f "$(SETTINGS)"; then uv run marketsieve --settings "$(SETTINGS)" market capture --market "$(MARKET)" --session "$(SESSION)" $(EVIDENCE) --history-days "$(HISTORY_DAYS)" --output json; else uv run marketsieve market capture --market "$(MARKET)" --session "$(SESSION)" $(EVIDENCE) --history-days "$(HISTORY_DAYS)" --output json; fi

market-reconstruct: ## Reconstruct price evidence for MARKET and AS_OF=YYYY-MM-DD.
	@test -n "$(AS_OF)" || { echo "AS_OF is required" >&2; exit 2; }
	uv run marketsieve market reconstruct --market "$(MARKET)" --date "$(AS_OF)" --history-days "$(HISTORY_DAYS)" --output json

market-resume: ## Resume an interrupted Snapshot run by RUN_ID.
	@test -n "$(RUN_ID)" || { echo "RUN_ID is required" >&2; exit 2; }
	@if test -f "$(SETTINGS)"; then uv run marketsieve --settings "$(SETTINGS)" market build --resume "$(RUN_ID)" --output json; else uv run marketsieve market build --resume "$(RUN_ID)" --output json; fi

market-list: ## List verified stored Snapshots.
	uv run marketsieve market list --output json

market-show: ## Show SNAPSHOT=latest or an exact Snapshot.
	uv run marketsieve market show "$(SNAPSHOT)" --output json

market-preview: ## Preview one Snapshot Explorer over loopback HTTP.
	uv run marketsieve preview "snapshot:$(SNAPSHOT)" --port "$(PORT)" --open

market-query: ## Query a stored Snapshot; set QUERY_ARGS explicitly.
	uv run marketsieve market query --snapshot "$(SNAPSHOT)" $(QUERY_ARGS) --output json

market-security: ## Show INSTRUMENT=MIC:SYMBOL from a stored Snapshot.
	@test -n "$(INSTRUMENT)" || { echo "INSTRUMENT is required" >&2; exit 2; }
	uv run marketsieve market security "$(INSTRUMENT)" --snapshot "$(SNAPSHOT)" --output json

market-compare: ## Compare space-separated INSTRUMENTS in a stored Snapshot.
	@test -n "$(INSTRUMENTS)" || { echo "INSTRUMENTS is required" >&2; exit 2; }
	uv run marketsieve market compare $(INSTRUMENTS) --snapshot "$(SNAPSHOT)" $(FIELDS) --output json

market-diff: ## Compare LEFT_SNAPSHOT and RIGHT_SNAPSHOT.
	@test -n "$(LEFT_SNAPSHOT)" && test -n "$(RIGHT_SNAPSHOT)" || { echo "LEFT_SNAPSHOT and RIGHT_SNAPSHOT are required" >&2; exit 2; }
	uv run marketsieve market diff "$(LEFT_SNAPSHOT)" "$(RIGHT_SNAPSHOT)" $(FIELDS) --output json

research-build: ## Build research for space-separated INSTRUMENTS from SNAPSHOT.
	@test -n "$(INSTRUMENTS)" || { echo "INSTRUMENTS is required" >&2; exit 2; }
	@if test -f "$(SETTINGS)"; then uv run marketsieve --settings "$(SETTINGS)" research build $(INSTRUMENTS) --snapshot "$(SNAPSHOT)" $(RESEARCH_EVIDENCE) --history-days "$(RESEARCH_HISTORY_DAYS)" --output json; else uv run marketsieve research build $(INSTRUMENTS) --snapshot "$(SNAPSHOT)" $(RESEARCH_EVIDENCE) --history-days "$(RESEARCH_HISTORY_DAYS)" --output json; fi

research-list: ## List stored research packs.
	uv run marketsieve research list --output json

research-show: ## Show RESEARCH_ID; latest also needs INSTRUMENT and SNAPSHOT.
	@if test "$(RESEARCH_ID)" = latest; then test -n "$(INSTRUMENT)" || { echo "INSTRUMENT is required for latest" >&2; exit 2; }; uv run marketsieve research show latest --security "$(INSTRUMENT)" --snapshot "$(SNAPSHOT)" --output json; else uv run marketsieve research show "$(RESEARCH_ID)" --output json; fi

research-preview: ## Preview one Research Explorer over loopback HTTP.
	@if test "$(RESEARCH_ID)" = latest; then test -n "$(INSTRUMENT)" || { echo "INSTRUMENT is required for latest" >&2; exit 2; }; uv run marketsieve preview research:latest --security "$(INSTRUMENT)" --port "$(PORT)" --open; else uv run marketsieve preview "research:$(RESEARCH_ID)" --port "$(PORT)" --open; fi

sync: ## Install the locked workspace and development dependencies.
	uv sync --locked
	uv run python -m scripts.runtime_wheelhouse prepare --output "$(STATE_DIR)/cache/runtime-wheelhouse"

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

secret-check: ## Scan tracked files and the current diff without printing values.
	uv run python -m scripts.secret_gate --base "$(BASE_SHA)"

check: ## Run the complete development gate with bounded parallel workers.
	BASE_SHA="$(BASE_SHA)" EVIDENCE_DIR="$(EVIDENCE_DIR)" GATE_JOBS="$(GATE_JOBS)" uv run python -m scripts.develop_gate check all --jobs "$(GATE_JOBS)"

capabilities-json: ## Describe the CLI machine contract.
	uv run marketsieve capabilities --output json

build: ## Build all public distributions under generated state.
	uv run python -m scripts.package_catalog build --out-dir "$(STATE_DIR)/artifacts/build"

evidence: check evidence-bundle ## Run the gate and create a review bundle.

evidence-bundle: ## Create a full or reviewed-SHA delta semantic review bundle.
	uv run python -m scripts.review_gate create --base-sha "$(BASE_SHA)" --head-sha "$(HEAD_SHA)" --evidence-dir "$(EVIDENCE_DIR)" --output-dir "$(REVIEW_DIR)" $(if $(PREVIOUS_REVIEWED_SHA),--reviewed-sha "$(PREVIOUS_REVIEWED_SHA)",)

evidence-validate: ## Validate BUNDLE=<review-bundle-directory>.
	uv run python -m scripts.review_gate validate "$(BUNDLE)"

review-attest: ## Publish the reviewed HEAD status.
	@test -n "$(REVIEWED_SHA)" || { echo "REVIEWED_SHA is required" >&2; exit 2; }
	uv run python -m scripts.review_attestation attest --reviewed-sha "$(REVIEWED_SHA)"

governance-check: ## Compare checked-in rulesets with active GitHub settings.
	uv run python -m scripts.governance_gate verify

release-build: ## Build VERSION at COMMIT once.
	@test -n "$(VERSION)" && test -n "$(COMMIT)" || { echo "VERSION and COMMIT are required" >&2; exit 2; }
	uv run python -m scripts.release_gate build --version "$(VERSION)" --commit "$(COMMIT)" --dist-dir "$(RELEASE_DIR)"

release-verify: ## Verify an existing release directory.
	python3 -m scripts.release_gate verify --version "$(VERSION)" --commit "$(COMMIT)" --dist-dir "$(RELEASE_DIR)"

release-check: release-build release-verify ## Build once and verify a release candidate.
