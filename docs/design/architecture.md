# Architecture

## Purpose

The architecture makes a broad equity matrix reproducible, inspectable, and safe for AI-assisted
analysis. Pure market calculations remain independent from provider I/O. The application composes
one explicit yfinance adapter with immutable local storage and deterministic projections.

## Package boundaries

`marketsieve` is the public SDK. It owns exchange-qualified instruments, market observations,
Decimal-based calculations, matrix field definitions, and pure daily or weekly decision policies.
It does not import the CLI, extension API, configuration, logging, network clients, databases,
delivery providers, or model providers.

`marketsieve-extension-api` owns small provider-facing contracts. The matrix contract consists of
`EquityBatchRequest`, `EquityBatchObservation`, `EquityAcquisitionFailure`, `ImportedEquityBatch`,
and `EquityBatchFetcher`. Requests and responses use SDK values and preserve exact requested
instruments. The existing single-instrument and generic-universe contracts remain separate because
they serve non-matrix workflows.

`marketsieve-source-yfinance` is the sole runtime matrix adapter. It translates one batch request
into multi-symbol adjusted daily prices and bounded per-symbol profile and statement requests. It
normalizes provider exceptions into stable failure codes and never selects another source.

`marketsieve-cli` owns configuration, entry-point discovery, orchestration, persistence, schemas,
console output, and generated projections. Application modules depend on protocols, not concrete
output adapters. The composition root supplies the yfinance registry, configuration reader, and
matrix repository.

Other source packages, portfolio importers, snapshots, routine reports, and experiments remain
independent capabilities. The matrix application does not consult them during acquisition or
recovery.

## End-to-end matrix flow

```text
versioned constituent assets
    -> deduplicate by MIC:SYMBOL identity and retain index memberships
    -> EquityBatchRequest (three years, daily, adjusted)
    -> yfinance price batches + bounded profile/financial acquisition
    -> ImportedEquityBatch with observations and exact failures
    -> pure common-field calculation + benchmark-relative calculation
    -> canonical rows, definitions, summary, failures, and manifest
    -> immutable content-addressed matrix object
    -> CSV / self-contained HTML / aggregate Markdown projections
    -> analysis-context/v2 references for external agents
```

## Constituent assets

`marketsieve_cli.resources/index_universe.json` is a versioned product asset, not a market-data
provider. Each index records its name, benchmark symbol, as-of date, source URL, source hash,
constituent count, exchange-qualified identifier, and yfinance symbol. Runtime loading validates the
stored count and deduplicates overlapping constituents while retaining multiple memberships.

The benchmark mapping is fixed: `^N225`, `^TOPX`, `^GSPC`, `^DJI`, and `^NDX`. A failed benchmark
remains missing. No proxy index is allowed.

## Acquisition boundary

Prices use `interval=1d`, `auto_adjust=True`, and `actions=True` explicitly. Symbols are grouped by
the configured batch size. For an adjusted series, each stock-split ratio is applied to volumes
before that split date and the split-equivalent result is rounded half-even to the integer-share
daily-bar contract. This preserves adjusted-close traded value across splits; an invalid split
action rejects the history instead of silently using incompatible price and volume bases. Invalid
or empty provider rows are rejected; they are not repaired. Company and
financial requests use bounded concurrency, timeout, retry count, and exponential base wait from
the matrix configuration. A same-date daily row is excluded until the exchange calendar's close for
that exact date, including scheduled shortened sessions, so an in-progress session is never treated
as a daily close. The calendar library supplies trading-session rules only; yfinance remains the
sole runtime source of prices, company information, and financial statements.
The latest accepted date for each security must reach the latest date observed for its JP or U.S.
market in the same yfinance batch. A market-wide reference more than seven calendar days behind the
request end is also stale. These histories receive `stale_history` and do not contribute to price
coverage. Because yfinance converts an absent daily volume to zero before returning its frame, a
zero in a required 20- or 60-session window is conservatively treated as unavailable; affected
liquidity cells receive `field_absent` instead of using the ambiguous zero.

An observation preserves the original requested instrument, provider symbol, memberships,
retrieval time, normalized bars, profile values, financial values, and source evidence hash. The
imported batch covers every requested instrument, including benchmarks. Request-level and
field-level failures retain stage, field, and normalized reason.

## Calculation boundary

The SDK field catalog is common to every row. It describes each name, group, type, unit, source,
definition, formula, period, and definition version. Price-derived calculations align observations
by trading date. Returns are simple returns. Volatility uses sample standard deviation of log
returns annualized by 252. Relative return is the security return minus the matching index return.
Beta is common-date sample covariance divided by benchmark sample variance.

All numeric serialization follows the existing Decimal policy. A field is valid only when its
required history and denominator exist. Otherwise the row records one stable missing code such as
`symbol_not_found`, `history_empty`, `stale_history`, `insufficient_history`, `zero_denominator`,
`field_absent`, `financials_unavailable`, `rate_limited`, `network_error`, or `provider_error`.
Values and missing codes are mutually exclusive and exhaustive for the field catalog.

## Persistence and identity

Completed objects live below `.marketsieve/matrices/objects/MATRIX_ID`. The semantic identity is a
SHA-256 over the constituent asset definitions, configuration, field definitions, source version,
input snapshot ID, canonical row hashes, index summary, and failure records. An existing object is
verified before reuse and is never mutated.

`securities.jsonl` contains authoritative `market-matrix-security/v1` rows. `fields.json`,
`market-matrix-manifest/v1` `manifest.json`, `index-summary.json`, and
`failures.jsonl` are canonical supporting evidence. `matrix.csv`, `overview.html`, and `analysis.md`
are generated from those structures in the same write transaction. The HTML embeds its styles,
script, and data; it performs no external request. CSV represents a missing value as an empty cell
and preserves its code in `missing_fields_json`.

The completed manifest retains the exact request fingerprint, acquisition window, selected assets,
settings, adjustment policy, and source profile before the transient run is removed.

Runs live below `.marketsieve/matrices/runs`. Run initialization atomically exposes a canonical
request fingerprint before network work. `--resume` accepts only that fingerprint, reuses its
original date window, and is limited to the original local acquisition date. Every refresh also
rechecks the local date after acquisition and rejects a run that crossed midnight, so current
profile and statement values cannot be combined with a price window from another date. Completed
storage first commits and verifies that request evidence in the immutable object, atomically updates
the latest reference while the run remains recoverable, and then removes the transient run. A run
cleanup failure does not invalidate or hide an already published immutable object.

## Offline views and analysis

`matrix show` verifies semantic identity and required projections. `matrix row` and
`matrix compare` load verified canonical rows only. They neither call a provider nor invoke a
calculation function. Comparison is an explicit selection of already stored cells and missing codes.

The matrix's `index-summary.json` aggregates overall and per-index coverage, market breadth,
distributions, market-cap concentration, sector composition, and missingness. `analysis.md` renders
that evidence in a stable macro-oriented narrative without security recommendations.

`AnalysisWorkspace` writes `analysis-context/v2` below the isolated `.marketsieve/analysis/v2`
root. It contains the chosen matrix ID, counts, coverage, quality status, and relative paths to
canonical inputs, while deliberately excluding a second copy of the security rows. The workspace
verifies its own content identity, Markdown projection, and matrix reference on read. Files directly
below the legacy analysis root remain untouched and are never read by the v2 workspace.

## Routine analysis and extension isolation

Portfolio, watchlist, daily, weekly, generic snapshot, and experiment services keep their own
stores and schemas. Routine indicator calculators may reuse SDK primitives, but removed screen,
single-security inspection, public indicator calculation, and legacy equity comparison entry points
have no composition-root registration. Existing files from those removed paths are not deleted and
cannot influence matrix identity or current routine results.

Source plugins are discovered through package metadata. Metadata inspection does not import plugin
code. A plugin is loaded only for an explicit working capability. The CLI validates imported
responses against the exact request before persisting any normalized snapshot.
