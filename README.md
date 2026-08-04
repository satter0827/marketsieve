# MarketSieve

[![CI](https://github.com/satter0827/marketsieve/actions/workflows/ci.yml/badge.svg)](https://github.com/satter0827/marketsieve/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

MarketSieve is an open-source Python foundation for reproducible analysis of Japanese and U.S.
equities. The public SDK and the repository-local operational application have separate dependency
boundaries so market logic can remain independent from data providers, report agents, and delivery
channels.

[日本語版 README](README.ja.md)

## Purpose

MarketSieve will turn verified market facts into reproducible analyses, historical experiments,
and evidence-backed reports. Reports will be delivered through replaceable channels without making
the SDK depend on email, LINE, an LLM provider, or a database.

## Current status

The Offline Analysis Preview is complete. The public `marketsieve` package exposes validated
exchange-qualified instruments, daily-bar contracts, deterministic Japanese and U.S. synthetic
sources, and SMA20 state-change analysis. The repository-local application exposes the full path as
an offline demo; it is not an investment recommendation.

## Installation

Python 3.12 through 3.14 is supported. Development uses Python 3.13 and
[uv](https://docs.astral.sh/uv/).

```shell
make sync
```

The public SDK can be built independently:

```shell
make build
```

## CLI

The CLI belongs to the repository-local application and is not included in the public SDK wheel.
Its current commands perform no network requests and require no secrets.

```shell
uv run marketsieve --version
make doctor
make demo
make demo-json
```

`make demo` prints the fixed JP-then-US human view. `make demo-json` emits the versioned machine
contract with input range, observation counts, state, transition, provenance, and evidence ID.

## Architecture

The public SDK lives under `packages/core`. The operational application lives under
`apps/marketsieve` and depends on the SDK. The SDK cannot import the application or infrastructure
libraries. See the [documentation index](docs/README.md) and formal
[Architecture](docs/design/architecture.md) for the dependency rules.

## Development

The Makefile is the shared entry point for people, coding agents, VS Code, and CI. Use `make help`
to list the available operations. Run tests and the complete local gate before opening a pull
request:

```shell
make test
make check
make review
```

VS Code uses the workspace `.venv` and provides tasks for dependency sync, formatting, the current
test file, diagnostics, and the complete gate. Local caches and generated artifacts are kept under
`.marketsieve`; `.venv` is the only generated environment at the repository root.

`make check` runs the Develop Gate. `make review` additionally creates a checksummed review bundle
under `.marketsieve/artifacts/review/<commit>/`. Application results use stdout and structured JSON
Lines logs use stderr. Pass `--log-level INFO` to collect informational evidence and `--log-file`
to also retain it under `.marketsieve/logs/`.

Changes move through short-lived branches into `develop`. A human-reviewed `develop -> main` pull
request is the release boundary. See [Contributing](CONTRIBUTING.md) for the workflow.

## Roadmap

The next milestone turns the completed preview into a `0.1.0` candidate with historical replay and
channel-neutral reporting. See the [Roadmap](docs/roadmap.md) and the
[formal design](docs/design/README.md).

## License

MarketSieve is licensed under the [MIT License](LICENSE).
