# Architecture

## Purpose

MarketSieve separates reusable market semantics from one maintainer's operational environment. The
public SDK remains usable without provider credentials, configuration sources, logging setup,
network clients, databases, delivery providers, or LLM providers.

## Current components

The root workspace catalog declares every public distribution, and all entries share one version.
`marketsieve` contains the I/O-independent SDK, including knowledge-time-correct financial-history
calculations. `marketsieve-extension-api` defines the implemented daily-bar import contract,
`marketsieve-source-csv` implements local import, `marketsieve-source-jquants` implements explicit
J-Quants API V2 acquisition, `marketsieve-source-alphavantage` implements explicit Alpha Vantage
acquisition, `marketsieve-source-fred` implements explicit FRED economic-series acquisition,
`marketsieve-source-sec` implements explicit SEC filing and company-fact acquisition, and
`marketsieve-source-edinet` implements explicit EDINET filing and XBRL-derived acquisition.
`marketsieve-cli` owns the executable application and immutable
snapshot store.
The optional `marketsieve-agent` distribution implements decision-report fact selection,
deterministic safe fallback, and an injectable LM Studio OpenAI-compatible adapter. LM Studio uses
one bounded non-streaming request, follows no redirects, and accepts only loopback endpoints unless
remote access is separately allowed. OpenAI uses its fixed Responses endpoint only after explicit
cloud consent, disables storage and tools, and has an independent mocked-transport contract. The
Anthropic adapter separately implements the fixed Messages API, API-version, authentication, and
text-block contract with the same consent and request bounds. Google uses the fixed Gemini
Interactions endpoint, header-based authentication, JSON response format, and a completed
single-text contract. The CLI loads this optional distribution only for provider diagnostics and
`report explain`, derives
its fact catalog only from an immutable decision report, omits quantities and acquisition prices,
and never gives a model tools, source access, or calculation ownership. The CLI persists model and
template output below `.marketsieve/explanations` without modifying report objects.

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

The core returns typed normalized values, indicator results, and evidence and does not depend on
logging, clocks, handlers, files, or environment variables. The bootstrap owns logging
configuration and output destinations; command interfaces keep results on stdout and diagnostics
on stderr.

## Equity workbench path

The current application implements this vertical path in dependency order:

```text
Explicit source fetch or import
    -> immutable normalized snapshots
    -> deterministic seven-indicator analysis
    -> independent equity sections
    -> inspect / analyze / compare / report
    -> Japanese or English Rich, text, or JSON output
```

The application verifies stored objects before reconstructing SDK values. `inspect` is the shared
sectioned equity view. `analyze` projects one generic indicator, `compare` applies explicit
comparability checks, and `report` is a durable projection of the same sections. None performs
network access, implicit refresh, provider fallback, scoring, or recommendation.

A single source abstraction covering daily bars, intraday bars, quotes, fundamentals, corporate
actions, and instrument search is prohibited. Each future data kind earns a separate boundary from
a working use case.

## Source extension policy

Synthetic data is provider- and network-independent and belongs with the SDK testing and
demonstration support. The SDK depends on `tzdata` so exchange timezones remain available on Python
installations without an operating-system timezone database.
Analysis and synthetic modules do not reference one another; the application combines them through
the daily-source contract.
Sources that perform file or network I/O are separate distributions. CSV, J-Quants, Alpha
Vantage, FRED, SEC, and EDINET are working sources.

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
calls only the data-kind endpoints selected by an explicit configured profile. Price uses
`/equities/master` and `/equities/bars/daily`; financial facts use `/fins/summary`; events use
`/equities/earnings-calendar` and, only when configured, `/fins/dividend`. Contract tests inject a
synthetic HTTP transport and never connect to the network.

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

## Alpha Vantage acquisition path

`marketsieve-source-alphavantage` supports explicitly selected XNAS and XNYS instruments through
the fixed official query endpoint. Raw daily bars use `TIME_SERIES_DAILY`. Adjusted daily bars use
the premium `TIME_SERIES_DAILY_ADJUSTED` endpoint and apply its adjusted-close factor to OHLC while
adjusting volume only for subsequent split coefficients. `outputsize=full` and adjusted acquisition
require `plan=premium`; an unsupported request fails without retry, shortening, or substitution.

Company identity comes from `OVERVIEW`. Financial facts come from `INCOME_STATEMENT`,
`BALANCE_SHEET`, `CASH_FLOW`, and `EARNINGS`. Omitted fiscal starts, accounting standards,
consolidation bases, revision states, and publication instants remain explicitly unknown and
retrieval-bounded. Events use explicitly selected `EARNINGS`, `DIVIDENDS`, and `SPLITS` endpoints.
Every data kind validates the requested symbol, MIC, and equity classification against `OVERVIEW`
before accepting provider facts. Contract tests inject a synthetic transport and do not contact
the provider.

Daily bars, financials, and events are stored as independent content-addressed objects and have
independent mutable references. A failed or unavailable data kind does not overwrite another kind.
Financial records preserve fiscal boundaries, publication time, consolidation, revision, currency,
scale, provider field, normalized concept, and an optional filing link. Filing records separately
preserve provider document and issuer identities, amendment linkage, publication time, and stated
accounting dimensions. Earnings schedules without a provider publication
timestamp use retrieval availability. Split events come only from the explicitly selected
`SPLITS` endpoint and are never inferred from adjusted-price factors; an unselected or unavailable
event kind remains missing.

## FRED acquisition path

`marketsieve-source-fred` implements only the official HTTPS
`fred/series/observations` endpoint. One request fixes the series ID, observation range, historical
knowledge date, raw-level transformation, ascending order, and page size. The same knowledge date
is sent as both real-time bounds. Provider rows retain their inclusive real-time revision interval,
and rows outside the requested observation or knowledge bounds are rejected.

The adapter reads `FRED_API_KEY` from the invoking environment and never stores it in a request or
result. Pagination must reach the provider's declared count without duplicates, gaps in progress,
or a changing total. The provider's `.` marker becomes an explicit missing date. HTTP
authentication, redirect, rate-limit, malformed-response, and safety-limit failures stop the exact
request without retry, transformation, series substitution, or fallback. Tests inject the
transport and do not contact FRED.

## SEC acquisition path

`marketsieve-source-sec` reads only the official filer submissions and XBRL company-facts JSON
resources on `data.sec.gov`. A profile supplies one ten-digit CIK and supported periodic forms.
The adapter never infers a CIK from a ticker, downloads filing documents, or evaluates custom
taxonomies. Additional submission-history files are fetched only when their declared date range
overlaps the exact request.

Every request carries the operator-supplied `SEC_USER_AGENT` organization and contact value required
for fair access. The value is sent only in the header and is not retained. Redirects, fair-access
rejections, rate limits, missing resources, oversized payloads, and malformed responses fail
without retry or fallback.

Each accepted filing retains its accession number, SEC acceptance instant, form, report end, and an
unambiguous amendment link when the original filing is present in the same result. Supported
US-GAAP and IFRS company facts retain taxonomy tags, units, periods, values, and accession links.
The adapter maps only named standard concepts, rejects conflicting duplicates, and never derives
cash flow or other values inside the source.

## EDINET acquisition path

`marketsieve-source-edinet` reads only the official EDINET v2 document-list and document endpoints.
A profile supplies one EDINET code, supported periodic-report type codes, date and document bounds,
and no provider URL. The adapter never infers an EDINET code from a ticker or executes an
issuer-specific taxonomy rule.

The API key enters through `EDINET_API_KEY` and is sent only as the official
`Subscription-Key` query parameter. Responses retain only cryptographic identity, normalized
filings, and facts. Redirects, authentication failures, application-level errors, rate limits,
oversized responses, unsafe ZIP paths, expansion bounds, encoding errors, and conflicting facts
stop the request without retry or fallback.

One list request is made for every explicitly requested calendar date. Matching documents must
belong to the configured EDINET code, have XBRL-derived CSV, remain viewable, and fit the configured
document budget. Each filing preserves document ID, Japanese submission instant, parent-document
link, period, and type. Standard J-GAAP, IFRS, and US-GAAP rows retain the provider element ID,
current-period scope, consolidated or non-consolidated basis, unit, value, and filing link.

Source registration, priority, fallback, authentication, retries, rate-limit handling, caching,
and provider-symbol mapping belong to the application or adapter packages. A source must not:

- shorten a requested range and report complete success;
- substitute raw data for an adjusted request or change frequency;
- guess a market from a symbol;
- merge providers or conflicting values without an explicit application use case;
- hide authentication, authorization, invalid-response, or data-conflict failures through fallback.

## Packaging boundary

The supported build produces an independent wheel and source distribution for every public-package
catalog entry. Explicit package manifests prevent sibling
package code, tests, local configuration, caches, notes, and generated reports from crossing
artifact boundaries. The complete wheel set is installed offline in an isolated environment.
Source dependencies do not expand the core SDK.

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
comparison and legacy equity rendering read verified snapshots and never trigger an implicit
refresh. Model explanation reads a verified decision report instead. Mutable references are
rebuildable indexes and are not evidence authorities.

An equity view is a composition of independent instrument, price, technical, financial, valuation,
risk, event, and data-quality sections. Each section owns status, completeness, missing reasons,
provenance, and evidence. There is no universal market-data source and no monolithic snapshot object
that requires every data kind to succeed.

Shareable non-secret configuration lives in `marketsieve.toml`. Generated state, snapshots, logs,
caches, and artifacts live below `.marketsieve`. Credentials enter only through provider-specific
environment variables and are never copied into configuration, snapshots, logs, review evidence,
or distributions.

## Model explanation boundary

The optional `marketsieve-agent` distribution consumes a validated decision report. Provider
packages remain outside the SDK. A model chooses fact identifiers,
section order, and bounded non-numeric connective text; a deterministic renderer inserts factual
values and evidence. The agent owns no source, calculation, file, tool, delivery, or trading access.

Test-local models validate the application pipeline without entering production selection. Each
real provider has separate mocked-transport contract tests. LM Studio is local and loopback-only
by default. Cloud use requires an explicit invocation flag and never becomes a fallback for a
failed local or cloud provider.

## Decision report storage

The report becomes the application boundary for routine use:

```text
Explicit acquisition or import
    -> verified immutable data snapshots
    -> brokerage-neutral portfolio snapshot
    -> typed analysis context
    -> deterministic decision policy
    -> immutable decision report
    -> Rich, text, JSON, Markdown, or optional model explanation
```

The SDK owns portfolio, policy, decision, evidence, and report semantics without owning a clock,
configuration, persistence, provider, renderer, or LLM. The CLI adapter serializes
`decision-report/v1` as canonical sorted JSON, derives its SHA-256 report ID from semantic content,
and generates deterministic Markdown from the validated report. The JSON object is evidence
authority; Markdown and latest references are replaceable indexes and projections.

Reports live below `.marketsieve/reports`. Immutable JSON objects use `objects/<report_id>.json`,
Markdown uses `rendered/<report_id>.md`, and session references use
`refs/{jp-latest,us-latest,weekly-latest}.json`. Writes use a temporary sibling and atomic replace.
A report containing only indeterminate decisions remains inspectable but does not advance a latest
reference. Reads reconstruct and validate SDK values and reject non-canonical or modified content.
When a report references a previous report, the store requires that exact immutable object before
writing or verifying Markdown. The projection classifies a current decision as changed only when
its action or confidence differs, classifies equal decisions as unchanged, and shows instruments
entering or leaving the reviewed portfolio explicitly.

## Personal Close Brief application architecture

The CLI currently imports one strict broker-neutral UTF-8 CSV into a brokerage-neutral portfolio
snapshot and a content-addressed local store. It retains only normalized values and the source
SHA-256 digest. The source file is never copied below `.marketsieve`. The extension API adds
portfolio import only with a working Rakuten package. Its implemented
economic-series capability is provided by the independently installable FRED package. The CLI owns
source selection and report orchestration in addition to content-addressed storage and Markdown
presentation. The implemented daily service selects one currency-qualified market from the latest
portfolio and explicitly fetches price, financial, and event data for each instrument through one
configured profile. It filters every input to the command knowledge time, projects compatible
annual financial periods through the SDK financial-history calculation, selects the next known
earnings date, evaluates the shared policy, and stores the report. Price acquisition is essential:
a failed instrument is evaluated with empty price history and remains visibly indeterminate.
Financial and event acquisition are optional evidence; failures lower confidence or omit the
earnings wait rule and remain visible as diagnostics. An all-indeterminate run stores diagnostic
evidence without advancing the session reference.

The weekly service performs no acquisition. It reads the explicit Japanese-close and U.S.-close
latest references, rejects missing, future, or stale inputs, and combines their decisions without
recalculation. The weekly report records both sorted input report IDs in its canonical JSON; those
IDs therefore participate in the report digest. Daily reports cannot claim input report IDs, and a
weekly report requires exactly two.

Application use cases replace the growing snapshot-service orchestration surface. Acquisition,
portfolio import, daily reporting, weekly reporting, report lookup, and model explanation have
separate inputs and results. A small application-local content-addressed store may share atomic
write and checksum mechanics across data, portfolio, and report repositories; their normalized
schemas and validation remain separate.

The production agent consumes a validated decision report. It cannot fetch data, read portfolio
files, recalculate a decision, or replace a failed explanation with a different report. Test-model
behavior remains in tests only.

The root workspace package catalog is the authority for public distribution names, paths, import
packages, build order, and isolation checks. Build scripts and tests derive their package sets from
that catalog instead of maintaining independent lists.
