# Architecture

## Purpose

MarketSieve separates reusable market semantics from one maintainer's operational environment. The
public SDK remains usable without provider credentials, configuration sources, logging setup,
network clients, databases, delivery providers, or LLM providers.

## Current components

The repository builds five public distributions at the same version. `marketsieve` contains the
I/O-independent SDK. `marketsieve-extension-api` defines the implemented daily-bar import contract,
`marketsieve-source-csv` implements local import, `marketsieve-source-jquants` implements explicit
J-Quants API V2 acquisition, and `marketsieve-cli` owns the executable application and immutable
snapshot store.

The `marketsieve_cli` package owns the command-line interface, offline diagnostics, use-case
orchestration, and console presentation. It is independently installable and is never included in
the SDK wheel.

```text
Interface
    |
    v
Bootstrap ---> Console adapter
    |               |
    v               v
Application service
    |
    v
marketsieve SDK
```

- The SDK contains domain semantics, deterministic analysis, channel-neutral results, and only
  those public ports that have a working implementation and tests.
- Application services own use-case orchestration and source-selection policy.
- Adapters own provider, file, persistence, delivery, and other I/O details.
- Interfaces translate external input and output and do not implement market rules.
- Dependencies point inward; the SDK never imports application or infrastructure packages.

## Executable module ownership

The CLI application uses one composition root. Command interfaces depend on
`marketsieve_cli.bootstrap`, the bootstrap module constructs application services, and application
services depend on the public SDK. Interfaces do not import application implementations directly,
and application services do not import bootstrap or interface modules.

Import Linter is the executable authority for layer direction and cycles between these components.
AST structure tests separately protect the SDK from I/O dependencies and protect the public
distribution boundary. New layers or public ports are added only with a working use case and tests;
empty adapter, repository, or base-class packages are prohibited.

The core returns typed results, replay, reports, and evidence and does not depend on logging, clocks, handlers,
files, or environment variables. Application services accept a standard-library `Logger` from the
composition root and emit records only at an application boundary. The bootstrap owns logging
configuration and output destinations; command interfaces keep results on stdout and logs on
stderr.

## Historical report path

The current application implements this vertical path in dependency order:

```text
Historical report command
    -> application orchestration
    -> synthetic daily-bar source
    -> independently loaded as-of snapshots
    -> deterministic SMA20 replay
    -> channel-neutral report
    -> Rich, text, or JSON console output
```

The legacy historical projection now delegates SMA calculation to the generic indicator engine.
Replay and report projection remain scheduled for removal when the section-based report replaces
this transitional command.

The daily-data boundary remains the small `DailyBarSource` structural protocol. Its capability model
describes whether an exact request is supported before retrieval. The protocol is public together
with the synthetic implementation and contract tests.

A replay accepts its evaluation schedule explicitly and reloads the source at every instant. The
application selects the synthetic schedule; the SDK validates and executes it. The console adapter
implements a private application output port. No public delivery port is introduced from one
console implementation.

A single source abstraction covering daily bars, intraday bars, quotes, fundamentals, corporate
actions, and instrument search is prohibited. Each future data kind earns a separate boundary from
a working use case.

## Source extension policy

Synthetic data is provider- and network-independent and belongs with the SDK testing and
demonstration support. The SDK depends on `tzdata` so exchange timezones remain available on Python
installations without an operating-system timezone database.
Analysis and synthetic modules do not reference one another; the application combines them through
the daily-source contract.
Sources that perform file or network I/O are separate distributions. CSV and J-Quants are working
sources. Alpha Vantage remains a roadmap candidate.

## CSV acquisition and snapshot path

The implemented offline acquisition path is:

```text
Manifest-backed CSV bundle
    -> explicitly loaded csv entry point
    -> validated daily-bar import result
    -> canonical normalized JSON
    -> content-addressed immutable object
    -> rebuildable source-profile reference
    -> price-only equity inspection
```

`source list` reads entry-point package metadata without importing plugin code. A separate entry-point
metadata group declares daily-bar fetch capability, so missing-snapshot guidance can distinguish
fetchers from import-only sources without executing plugin code. `source import` loads only the
named plugin. The CSV bundle declares instrument identity, MIC, timezone, currency, adjustment,
retrieval time, and availability basis; none is inferred from filenames or locale. Raw input is not
retained. Its digest is recorded beside normalized facts.

Objects are written below `.marketsieve/data/objects/<sha256>` through a temporary sibling
directory and an atomic rename. A manifest records the normalized checksum. `snapshot verify`
recomputes both the file checksum and canonical object identity. Profile references below
`.marketsieve/data/refs` are mutable indexes, not evidence authority. Pending directories are never
listed as snapshots.

Verified normalized bars are reconstructed as SDK `DailyBar` values before technical analysis.
The core indicator engine owns all seven calculations and evidence; snapshot adapters and CLI
renderers perform no indicator arithmetic. `analyze` returns one generic indicator result, while
`inspect` composes the default seven definitions into its technical section and reports
insufficient-history completeness explicitly.

## J-Quants acquisition path

`marketsieve-source-jquants` implements the individual J-Quants API V2 contract. It uses the fixed
`https://api.jquants.com/v2` origin, sends `JQUANTS_API_KEY` only in the `x-api-key` header, and
calls `/equities/master` and `/equities/bars/daily` only after an explicit configured profile is
selected. Contract tests inject a synthetic HTTP transport and never connect to the network.

The adapter accepts only `XTKS`/`JPY`/`Asia/Tokyo`, preserves the exact requested date range and
adjustment choice, follows explicit pagination, and rejects duplicate, out-of-range,
cross-instrument, or malformed observations. Null OHLCV records represent non-trading observations
and are excluded. Partially null OHLCV records are rejected as malformed. HTTP redirects are
rejected before any credential can be forwarded, including redirects to another origin.
Authorization, subscription, payload-size, and rate-limit responses fail explicitly and never
shorten or substitute a request.

Provider profile values are stored beside normalized bars with their observation date. Because the
responses do not expose a per-record publication timestamp, they use retrieval availability and
cannot enter an earlier knowledge-as-of analysis. Raw responses are never retained; only response
digests enter snapshot identity.

Source registration, priority, fallback, authentication, retries, rate-limit handling, caching,
and provider-symbol mapping belong to the application or adapter packages. A source must not:

- shorten a requested range and report complete success;
- substitute raw data for an adjusted request or change frequency;
- guess a market from a symbol;
- merge providers or conflicting values without an explicit application use case;
- hide authentication, authorization, invalid-response, or data-conflict failures through fallback.

## Packaging boundary

The supported build produces independent SDK, extension API, CLI, CSV source, and J-Quants source
wheels and source distributions. Explicit build allowlists prevent sibling package code, tests, local configuration,
caches, notes, and generated reports from crossing artifact boundaries. The complete wheel set is
installed offline in an isolated environment. Source dependencies do not expand the core SDK.

## Approved 0.2 target architecture

The workbench replaces the report-specific application path with acquisition, immutable storage,
deterministic analysis, section assembly, and independent projections:

```text
Provider or CSV package
    -> acquisition capability
    -> content-addressed snapshot store
    -> normalized SDK values
    -> independent equity sections
    -> inspect / analyze / compare / report
```

The target workspace contains the `marketsieve` SDK, a minimal `marketsieve-extension-api`, the
public `marketsieve-cli`, and independent CSV, J-Quants, and Alpha Vantage source distributions.
The extension API is introduced with the working CSV integration, not as an empty plugin framework.
The CLI and source packages depend inward through the extension API to the SDK. The SDK imports none
of them.

Source registration is explicit. Package metadata may be inspected without importing plugin code;
only a source profile selected for `doctor` or `fetch` may load its configured entry point. Loading
a Python plugin is equivalent to running any other trusted installed Python package and is not a
sandbox boundary.

Network acquisition and offline consumption are different use cases. `source fetch` and `source
import` create immutable objects below `.marketsieve/data/objects`. Inspection, analysis,
comparison, report rendering, and later agent rendering read verified snapshots and never trigger
an implicit refresh. Mutable references are rebuildable indexes and are not evidence authorities.

An equity view is a composition of independent instrument, price, technical, financial, valuation,
risk, event, and data-quality sections. Each section owns status, completeness, missing reasons,
provenance, and evidence. There is no universal market-data source and no monolithic snapshot object
that requires every data kind to succeed.

Shareable non-secret configuration lives in `marketsieve.toml`. Generated state, snapshots, logs,
caches, and artifacts live below `.marketsieve`. Credentials enter only through provider-specific
environment variables and are never copied into configuration, snapshots, logs, review evidence,
or distributions.

## Approved 0.3 target architecture

The optional `marketsieve-agent` distribution consumes the same validated section facts used by
the CLI. LangChain and provider packages remain outside the SDK. A model chooses fact identifiers,
section order, and bounded non-numeric connective text; a deterministic renderer inserts factual
values and evidence. The agent owns no source, calculation, file, tool, delivery, or trading access.

FakeListLLM validates the application pipeline but does not claim behavioral equivalence with chat
providers. Each real provider has separate mocked-transport contract tests. LM Studio is local and
loopback-only by default. Cloud use requires an explicit invocation flag and never becomes a
fallback for a failed local or cloud provider.
