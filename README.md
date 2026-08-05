# MarketSieve

[![CI](https://github.com/satter0827/marketsieve/actions/workflows/ci.yml/badge.svg)](https://github.com/satter0827/marketsieve/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

MarketSieve is an open-source Python foundation for reproducible analysis of Japanese and U.S.
equities. The public SDK and CLI application have separate dependency
boundaries so market logic can remain independent from data providers, report agents, and delivery
channels.

[日本語版 README](README.ja.md)

## Purpose

MarketSieve will turn verified market facts into reproducible analyses, historical experiments,
and evidence-backed reports. Reports will be delivered through replaceable channels without making
the SDK depend on email, LINE, an LLM provider, or a database.

## Current status

`0.3.0` is the release candidate on `develop`. It provides the complete data workbench:
independent CSV, J-Quants, and Alpha Vantage sources; immutable verified snapshots; price,
financial, and event inspection; seven deterministic technical indicators; and an explanation-only
Agent. FakeListLLM is the default. LM Studio and explicitly consented OpenAI, Anthropic, or Google
calls use the same grounded pipeline. The CLI presents evidence and missing-data reasons, not an
investment recommendation.

## Installation

Python 3.12 through 3.14 is supported. Development uses Python 3.13 and
[uv](https://docs.astral.sh/uv/).

```shell
make sync
```

The SDK, extension API, CLI, Agent, CSV source, J-Quants source, and Alpha Vantage source build as
independent artifacts:

```shell
make build
```

Published releases use a checksummed GitHub Release wheelhouse rather than PyPI. After verifying
the assets against `release.json`, extract the wheelhouse ZIP and install offline:

```shell
python -m pip install --no-index --find-links ./marketsieve-wheelhouse \
  "marketsieve-cli[all-sources]"
```

Install `marketsieve-cli[all]` from the same wheelhouse to include the optional Agent as well as all
sources.

## CLI

The public `marketsieve-cli` distribution depends on, but is not included in, the SDK wheel. Read
commands are offline. Only an explicit provider fetch reads its provider credential from the
environment and accesses the network.

```shell
uv run marketsieve --version
make doctor
make capabilities-json
```

`make capabilities-json` describes commands, options, schemas, exit codes, streams, and side
effects for AI clients. Inspection, analysis, comparison, and report commands read only verified
local snapshots; acquisition is always explicit.

The direct commands expose all output modes:

```shell
uv run marketsieve doctor --output json
uv run marketsieve capabilities --output json
uv run marketsieve source list --output json
uv run marketsieve source import ./example-bundle --output json
uv run marketsieve --config marketsieve.toml source fetch us XNAS:MSFT --start 2026-01-01 --end 2026-07-31 --output json
uv run marketsieve snapshot verify SNAPSHOT_ID --output json
uv run marketsieve inspect XTKS:7203 --source-profile offline-jp --output json
uv run marketsieve analyze rsi XTKS:7203 --period 14 --source-profile offline-jp --output json
uv run marketsieve compare XTKS:7203 XTKS:6758 --source-profile offline-jp --output json
uv run marketsieve report XTKS:7203 --source-profile offline-jp --format rich
uv run marketsieve agent explain XTKS:7203 --source-profile offline-jp --output json
uv run marketsieve --config marketsieve.toml agent explain XTKS:7203 --source-profile offline-jp --provider openai --dry-run --output json
```

## Architecture

The public SDK lives under `packages/core`, the implemented extension contract under
`packages/extension-api`, provider adapters under `packages/source-*`, and the CLI under
`packages/cli`. The SDK cannot import application or infrastructure libraries. See the
[documentation index](docs/README.md) and formal
[Architecture](docs/design/architecture.md) for the dependency rules.

## Development

The Makefile is the shared entry point for people, coding agents, VS Code, and CI. Use `make help`
to list the available operations. Run tests and the complete local gate before opening a pull
request:

```shell
make test
make check
make evidence
```

VS Code uses the workspace `.venv` and provides tasks for dependency sync, formatting, the current
test file, diagnostics, and the complete gate. Local caches and generated artifacts are kept under
`.marketsieve`; `.venv` is the only generated environment at the repository root.

`make check` runs the Develop Gate. `make evidence` additionally creates a checksummed review bundle
under `.marketsieve/artifacts/review/<commit>/`. Application results use stdout and structured JSON
Lines logs use stderr. Pass `--log-level INFO` to collect informational evidence and `--log-file`
to also retain it under `.marketsieve/logs/`.

Changes move through short-lived branches into `develop`. A human-reviewed `develop -> main` pull
request is the release boundary. See [Contributing](CONTRIBUTING.md) for the workflow.

## Roadmap

The 0.2 workbench and 0.3 grounded explanation Agent are complete on `develop`. See the
[Roadmap](docs/roadmap.md) and the [formal design](docs/design/README.md).

## License

MarketSieve is licensed under the [MIT License](LICENSE).
