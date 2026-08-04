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

The repository foundation is complete. The public `marketsieve` package currently exposes package
metadata only, and the repository-local application provides offline version and diagnostic
commands. The approved next milestone is an Offline Analysis Preview using synthetic Japanese and
U.S. daily data; market models and analysis are not current features.

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
Its current commands perform no network requests and require no secrets.

```shell
uv run marketsieve --version
uv run marketsieve doctor
```

## Architecture

The public SDK lives under `packages/core`. The operational application lives under
`apps/marketsieve` and depends on the SDK. The SDK cannot import the application or infrastructure
libraries. See the [documentation index](docs/README.md) and formal
[Architecture](docs/design/architecture.md) for the dependency rules.

## Development

Run the complete local gate before opening a pull request:

```shell
uv run pytest
uv run python scripts/quality_gate.py check all
```

Changes move through short-lived branches into `develop`. A human-reviewed `develop -> main` pull
request is the release boundary. See [Contributing](CONTRIBUTING.md) for the workflow.

## Roadmap

The next milestone completes a deterministic vertical path from synthetic Japanese and U.S. daily
data to an evidence-backed SMA20 state change and offline demo. See the
[Roadmap](docs/roadmap.md) for later milestones and the [formal design](docs/design/README.md) for
approved constraints.

## License

MarketSieve is licensed under the [MIT License](LICENSE).
