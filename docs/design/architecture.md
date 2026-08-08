# Architecture

## Product boundary

MarketSieve has two workflows: broad Market Snapshot acquisition and focused Security Research.
Both use yfinance only. No portfolio state, watchlist, scheduled judgment, score, ranking,
recommendation, or model output belongs to the product boundary.

`marketsieve` owns instruments, daily observations, Decimal calculations, field definitions, and
pure transformations. It does not import CLI, settings, logging, network, persistence, or provider
packages. `marketsieve-extension-api` owns typed provider contracts. `marketsieve-source-yfinance`
implements those contracts. `marketsieve-cli` owns explicit invocation inputs, optional operational
settings, orchestration, storage, projections, and console interfaces.

## Market Snapshot

Versioned constituent assets define Nikkei 225, TOPIX 500, S&P 500, Dow 30, and Nasdaq-100.
Constituents are deduplicated by `MIC:SYMBOL` while retaining overlapping memberships. Requested
evidence domains are acquired in batches and normalized without imputation. `1308.T` is the fixed
TOPIX-linked ETF proxy; it is not the TOPIX index and is never replaced at runtime.

Each content-addressed object contains `manifest.json`, `definitions.json`,
`quality-summary.json`, `quality-details.jsonl`, `quality-outliers.jsonl`,
`aggregates.jsonl`, `securities.jsonl`, `failures.jsonl`, `market-indicators.jsonl`, `README.md`,
`summary.md`, `explorer-data.json`, and `explorer.html`. `securities.jsonl` is the
one-security-per-line authority. JSONL and JSON are data; Markdown and HTML are deterministic
projections. No file references outside its object directory.

Storage owns canonical writing, hashing, and integrity verification. The Snapshot projection
builder creates reference-only `explorer-data/v4`. It declares sections, sources, views, filters,
column sets, fields, and saved-data actions while referring to canonical JSON and JSONL in the same
object. The shared renderer loads only those registered relative artifacts through the loopback
preview server. It supports line, horizontal bar, histogram, scatter, heatmap, and candlestick
views with table fallbacks and uses no external CDN. Market indicators use a separate extension
contract with explicit kind and unit; equity-only company, financial, market-cap, and volume checks
do not apply.

The object identity covers exact inputs, effective runtime settings, universe assets, definitions,
source evidence, rows, aggregates, failures, and artifact inventory. Interrupted runs can resume
only with the persisted request. Saved-data commands never contact the network or recalculate.

## Security Research

Research resolves explicit instrument IDs from an explicit Snapshot, then requests selected price,
company, financial, event, and benchmark evidence. Multiple instruments are independent: one
failure does not erase successful packs. Each immutable pack includes its source Snapshot context,
definitions, quality, failures, neutral summary, and object-folder-contained chart-led Explorer.
Research Explorer v4 stores only view metadata and relative references. The renderer loads the
authoritative object-local files through the restricted preview server and derives moving averages,
rolling risk, drawdown, and benchmark rebasing in the browser without acquisition or persistence.
Price, company, annual financial, quarterly financial, earnings, dividend, split, and benchmark
evidence have independent states so one failed provider endpoint cannot hide evidence from another.

Provider publication time is never invented. Retrieval-only facts state that availability basis.
Missing evidence remains missing. External AI interpretation cannot write back into evidence
objects.

The stable SDK is deliberately narrow: `marketsieve.model`, `marketsieve.indicators`, and
`marketsieve.fields`. The package root does not re-export all domain types, and the SDK does not
depend on provider, CLI, state, logging, or transport packages.

## Future transport

Application services accept typed inputs, an injected state root, and return schema-backed
documents without depending on Click, the current directory, or console formatting. Capabilities
are a transport-independent contract. Large operations return identities, summaries, counts, and
artifact references rather than placing complete JSONL streams in a response. A future MCP server
may expose the same use cases, but it must not introduce another domain, source selection rule, or
persistence format. No MCP SDK, server, or configuration is currently included.
