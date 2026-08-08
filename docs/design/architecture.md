# Architecture

## Purpose

MarketSieve produces reproducible broad-market Snapshots and focused Security Research Packs. Pure
market calculations remain independent from provider I/O. The application composes one explicit
yfinance adapter with immutable local storage and deterministic projections.

## Package boundaries

`marketsieve` is the public SDK. It owns instruments, observations, Decimal-based calculations,
field definitions, and pure decision policies. It does not import the CLI, extension API,
configuration, logging, network, storage, delivery, or model providers.

`marketsieve-extension-api` owns provider-facing contracts. `EquityBatchRequest` and
`ImportedEquityBatch` preserve every requested security and exact partial failures for broad
acquisition. `SecurityResearchRequest`, `ImportedSecurityResearch`, financial facts, events, and
`SecurityResearchFetcher` define focused acquisition without depending on a CLI or transport.

`marketsieve-source-yfinance` is the sole runtime market and research adapter. It translates typed
requests into yfinance calls, normalizes results and failures, and never selects another source.

`marketsieve-cli` owns configuration, entry-point discovery, orchestration, persistence, schemas,
console output, and generated projections. Application modules depend on protocols. The composition
root supplies registries, configuration readers, and repositories.

Portfolio, watchlist, routine report, generic snapshot, and experiment capabilities remain
independent. Market and research applications do not consult them during acquisition or recovery.

## Market Snapshot flow

```text
versioned constituent assets
    -> deduplicate MIC:SYMBOL and retain all index memberships
    -> EquityBatchRequest (three years, daily, adjusted)
    -> yfinance price batches + bounded profile and statement acquisition
    -> ImportedEquityBatch with observations and exact failures
    -> pure common-field and benchmark-relative calculations
    -> canonical securities, definitions, market, segments, quality, failures, manifest
    -> immutable content-addressed Market Snapshot
    -> verified README, CSV, HTML, and aggregate Markdown projections
```

`marketsieve_cli.resources/index_universe.json` is a versioned product asset, not a runtime
market-data source. It records each index, as-of date, source URL, hash, constituent identity, and
yfinance symbol. The fixed benchmarks are `^N225`, `1308.T`, `^GSPC`, `^DJI`, and `^NDX`.
`1308.T` is a TOPIX-linked ETF proxy rather than the TOPIX index. A failed benchmark remains missing.

Prices explicitly use `interval=1d`, `auto_adjust=True`, and `actions=True`. Split events adjust
volume onto the adjusted-price basis; inconsistent history is rejected as
`corporate_action_mismatch`. Exchange calendars determine whether a daily session has closed but do
not supply market values. Invalid, empty, stale, or partial results are recorded rather than repaired.

The common field catalog defines name, group, type, unit, source, definition, formula, period, and
definition version. Returns are simple returns. Volatility is the sample deviation of log returns
annualized by 252. Relative return is security return minus benchmark return. Beta is common-date
sample covariance divided by benchmark variance. Values and stable missing codes are mutually
exclusive and exhaustive for every field.

## Market Snapshot persistence

Completed objects live below `.marketsieve/market-snapshots/objects/SNAPSHOT_ID`. Their SHA-256
identity covers assets, configuration, definitions, source evidence, row hashes, market and segment
summaries, quality, failures, and artifact inventory. Existing objects are verified and never mutated.

`securities.jsonl` is the one-row-per-security authority. `manifest.json`, `definitions.json`,
`market.json`, `segments.jsonl`, `quality.json`, and `failures.jsonl` are canonical supporting
evidence. `README.md`, `securities.csv`, `explorer.html`, and `summary.md` are generated in one
transaction and verified on read. HTML has no CDN or runtime request. CSV preserves missing codes in
`missing_fields_json`.

Runs live below `.marketsieve/market-snapshots/runs`. `--resume` accepts only the original request
fingerprint and local acquisition date. Completed storage verifies the object, atomically publishes
`latest.json`, and then removes the run. A cleanup failure cannot hide a published object.

`market list`, `market show`, `market query`, `market security`, and `market compare` load verified
saved evidence only. They do not fetch, recalculate, or persist subsets. `market.json` provides all,
JP, and U.S. aggregates. `segments.jsonl` provides index, sector, and industry aggregates. README and
summary explain the contract without prescribing an agent's reasoning or conclusion format.

## Security Research boundary

Research begins with a security resolved from a verified Market Snapshot. The application requests
up to ten years of adjusted daily prices, retrieval-time company facts, annual and quarterly
statements, dividends, splits, and earnings events. Missing values are not imputed; another provider
is never selected.

Each result lives below `.marketsieve/research/objects/RESEARCH_ID`. `prices.jsonl`,
`financials.jsonl`, and `events.jsonl` are authoritative time-series evidence. `company.json`,
`market-context.json`, `definitions.json`, `quality.json`, and `failures.jsonl` describe scope,
availability, comparison context, and limitations. README, summary, and self-contained HTML are
verified projections. Publication time is never invented: facts without it are explicitly known
only at retrieval.

The pack contains no prompt, reasoning template, score, ranking, recommendation, or agent output.
External interpretations do not write into immutable evidence. A future MCP adapter is a transport
over the same application protocols and schemas, not a new domain, source, or persistence path.

## Extension isolation

Plugins are discovered through package metadata and loaded only for an explicit capability. The CLI
validates imported responses against the exact request before persistence. Removed public analysis
and screening paths have no composition-root registration and cannot influence current identities.
