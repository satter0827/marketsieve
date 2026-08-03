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

The repository is in its foundation stage. The public `marketsieve` package currently exposes
package metadata only. The repository-local application provides offline version and diagnostic
commands. Market models, indicators, experiments, reports, and delivery adapters are roadmap work,
not current features.

## Installation

Python 3.12 through 3.14 is supported. Development uses Python 3.13 and
[uv](https://docs.astral.sh/uv/).

```shell
uv sync --locked
```

The public SDK can be built independently:

```shell
uv build --package marketsieve
```

## CLI

The CLI belongs to the repository-local application and is not included in the public SDK wheel.
It performs no network requests and requires no secrets at the foundation stage.

```shell
uv run marketsieve --version
uv run marketsieve doctor
```

## Architecture

The public SDK lives under `packages/core`. The operational application lives under
`apps/marketsieve` and depends on the SDK. The SDK cannot import the application or infrastructure
libraries. See [Architecture](docs/architecture.md) for the dependency rules.

## Development

Run the complete local gate before opening a pull request:

```shell
uv run pytest
uv run python scripts/quality_gate.py check all
```

Changes move through short-lived branches into `develop`. A human-reviewed `develop -> main` pull
request is the release boundary. See [Contributing](CONTRIBUTING.md) for the workflow.

## Roadmap

The next milestone defines exchange-aware instruments and market-time semantics before adding
synthetic JP/US data, indicators, experiments, reports, or external services. See the
[Roadmap](docs/roadmap.md) for the ordered milestones.

## License

MarketSieve is licensed under the [MIT License](LICENSE).
