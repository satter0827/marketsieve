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

Each content-addressed object contains `manifest.json`, `definitions.json`, `quality.json`,
`aggregates.jsonl`, `securities.jsonl`, `failures.jsonl`, `market-indicators.jsonl`, `README.md`,
`summary.md`, `explorer-data.json`, and `explorer.html`. `securities.jsonl` is the
one-security-per-line authority. JSONL and JSON are data; Markdown and HTML are deterministic
projections. No file references outside its object directory.

Storage owns canonical writing, hashing, and integrity verification. Snapshot and Research
projection builders convert authoritative evidence into shared `explorer-data/v1`; the shared
renderer supports only line, horizontal bar, histogram, box plot, scatter, and heatmap views with
table fallbacks. It does not depend on the stores, yfinance, or Click. The HTML embeds the exact
projection and uses no external CDN.

The object identity covers exact inputs, effective runtime settings, universe assets, definitions,
source evidence, rows, aggregates, failures, and artifact inventory. Interrupted runs can resume
only with the persisted request. Saved-data commands never contact the network or recalculate.

## Security Research

Research resolves explicit instrument IDs from an explicit Snapshot, then requests selected price,
company, financial, event, and benchmark evidence. Multiple instruments are independent: one
failure does not erase successful packs. Each immutable pack includes its source Snapshot context,
definitions, quality, failures, neutral summary, and self-contained chart-led Explorer.

Provider publication time is never invented. Retrieval-only facts state that availability basis.
Missing evidence remains missing. External AI interpretation cannot write back into evidence
objects.

## Future transport

Application services accept typed inputs, an injected state root, and return schema-backed
documents without depending on Click, the current directory, or console formatting. Capabilities
are a transport-independent contract. Large operations return identities, summaries, counts, and
artifact references rather than placing complete JSONL streams in a response. A future MCP server
may expose the same use cases, but it must not introduce another domain, source selection rule, or
persistence format. No MCP SDK, server, or configuration is currently included.
