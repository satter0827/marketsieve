# MarketSieve

[![CI](https://github.com/satter0827/marketsieve/actions/workflows/ci.yml/badge.svg)](https://github.com/satter0827/marketsieve/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

MarketSieve is an open-source Python foundation for reproducible analysis of Japanese and U.S.
equities. The public SDK and CLI application have separate dependency
boundaries so market logic can remain independent from data providers, report agents, and delivery
channels.

[日本語版 README](README.ja.md)

## Purpose

MarketSieve turns verified market facts into reproducible analyses, historical experiments, and
evidence-backed reports. Replaceable application boundaries keep the SDK independent from email,
LINE, LLM providers, and databases.

## Current status

`develop` contains the 0.7.0 release candidate. It provides the data workbench:
independent CSV, J-Quants, Alpha Vantage, FRED, SEC, and EDINET sources; immutable verified
snapshots; price,
financial, and event inspection; seven deterministic technical indicators; and an explanation-only
Agent. Configured `daily jp` and `daily us` commands explicitly acquire portfolio instruments and
write immutable Close Brief reports. `weekly` combines eligible daily reports offline as the
weekend briefing. Daily reports use knowledge-time-correct financial trends and known earnings
dates when those optional source capabilities are configured. They also show known filing
amendments and company-relative valuation ranges built only from explicitly acquired local
history. The Agent reads only an immutable decision report and requires an explicit LM Studio,
OpenAI, Anthropic, or Google provider. Its output is stored separately and cannot change a report.
Bounded Japanese and U.S. universes can be updated explicitly, then screened offline from verified
local price snapshots. Candidate order exposes its inputs and never uses an opaque score. The
weekend briefing includes fresh stored candidates in a section separate from portfolio decisions.

## Installation

Python 3.12 through 3.14 is supported. Development uses Python 3.13 and
[uv](https://docs.astral.sh/uv/).

```shell
make sync
```

The SDK, extension API, CLI, Agent, CSV source, J-Quants source, Alpha Vantage source, FRED source,
SEC source, and EDINET source build as independent artifacts:

```shell
make build
```

Release artifacts are published both as a checksummed GitHub Release wheelhouse and as independent
PyPI distributions. Install the normal CLI and all source adapters from PyPI:

```shell
python -m pip install "marketsieve-cli[all-sources]>=0.7,<0.8"
```

For an offline installation, verify the GitHub Release assets against `release.json`, extract the
wheelhouse ZIP, and install without an index:

```shell
python -m pip install --no-index --find-links ./marketsieve-wheelhouse \
  "marketsieve-cli[all-sources]"
```

Install `marketsieve-cli[all]` from the same wheelhouse to include the optional Agent as well as all
sources.

## CLI

The public `marketsieve-cli` distribution depends on, but is not included in, the SDK wheel. Read
commands are offline. Explicit `source fetch` and `daily` acquisition read the selected provider
credential from the environment and access the network.

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
uv run marketsieve report list --output json
uv run marketsieve report show latest --output json
uv run marketsieve report export latest --format markdown
uv run marketsieve --config marketsieve.toml daily jp
uv run marketsieve --config marketsieve.toml weekly
uv run marketsieve experiment run strategy.toml --output json
uv run marketsieve experiment show RUN_ID --output json
uv run marketsieve experiment compare LEFT_RUN_ID RIGHT_RUN_ID --output json
uv run marketsieve experiment explain RUN_ID --provider lmstudio --output json
uv run marketsieve --config marketsieve.toml screen update jp --output json
uv run marketsieve --config marketsieve.toml screen run jp --output json
uv run marketsieve --config marketsieve.toml screen show latest --market jp --output json
uv run marketsieve --config marketsieve.toml report explain latest --provider openai --dry-run --output json
```

The canonical portfolio CSV header is
`kind,mic,symbol,currency,timezone,quantity,average_acquisition_price,account_type`.
Use `holding` with all fields or `watch` with the final three fields empty:

```shell
uv run marketsieve portfolio import holdings.csv --broker canonical \
  --as-of 2026-08-06T20:00:00+09:00
uv run marketsieve portfolio show
```

An empty Rakuten Securities `assetbalance(all)` export can be imported directly:

```shell
uv run marketsieve portfolio import assetbalance.csv --broker rakuten \
  --as-of 2026-08-06T12:48:40+09:00
```

MarketSieve stores normalized content and the input digest, not the source CSV. The Rakuten adapter
currently accepts only the verified no-holdings form. Use the canonical CSV for holdings and watch
items until an anonymized non-empty export defines that broker format.

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

## Plugin development

Provider packages depend on the small, data-kind-specific extension API rather than CLI internals.
The [external universe plugin example](examples/instrument-universe-plugin/README.md) is outside the
workspace catalog, declares `marketsieve-extension-api>=0.7,<0.8`, registers one entry point, and
uses the public conformance check. The complete gate builds its wheel and installs it against the
public wheel set in an isolated environment.

## Roadmap

See the [Roadmap](docs/roadmap.md) and the [formal design](docs/design/README.md).

## License

MarketSieve is licensed under the [MIT License](LICENSE).
