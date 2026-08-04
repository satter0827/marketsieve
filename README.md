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

`0.1.0` is the current public baseline. The next develop slice adds independently packaged CSV
import, immutable local snapshots, verification, and price inspection. The `marketsieve` package exposes validated
exchange-qualified instruments, daily-bar contracts, deterministic Japanese and U.S. synthetic
sources, SMA20 state-change analysis, time-correct historical replay, and channel-neutral reports.
The repository-local CLI presents the same evidence-backed report for people and machine clients;
it is not an investment recommendation.

## Installation

Python 3.12 through 3.14 is supported. Development uses Python 3.13 and
[uv](https://docs.astral.sh/uv/).

```shell
make sync
```

The SDK, extension API, CLI, and CSV source can be built as independent artifacts:

```shell
make build
```

## CLI

The public `marketsieve-cli` distribution depends on, but is not included in, the SDK wheel. Its
current commands perform no network requests and require no secrets.

```shell
uv run marketsieve --version
make doctor
make report
make report-json
make capabilities-json
```

`make report` uses a Rich terminal view when available and falls back to ANSI-free text when output
is redirected. `make report-json` emits the versioned report contract. `make capabilities-json`
describes commands, options, schemas, exit codes, streams, and side effects for AI clients.

The direct commands expose all output modes:

```shell
uv run marketsieve doctor --output json
uv run marketsieve report --market all --output rich
uv run marketsieve capabilities --output json
uv run marketsieve source list --output json
uv run marketsieve source import ./example-bundle --output json
uv run marketsieve snapshot verify SNAPSHOT_ID --output json
uv run marketsieve inspect XTKS:7203 --source-profile offline-jp --output json
```

## Architecture

The public SDK lives under `packages/core`, the implemented extension contract under
`packages/extension-api`, the CSV adapter under `packages/source-csv`, and the CLI under
`packages/cli`. The SDK cannot import the application or infrastructure
libraries. See the [documentation index](docs/README.md) and formal
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

The historical-report path is the `0.1.0` baseline. External data sources and personal delivery
channels remain later milestones. See the [Roadmap](docs/roadmap.md) and the
[formal design](docs/design/README.md).

## License

MarketSieve is licensed under the [MIT License](LICENSE).
