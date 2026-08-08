# Interfaces

## Root command

`marketsieve` uses exchange-qualified `MIC:SYMBOL` identifiers. JSON output uses versioned schemas;
human output is a projection. Market and research acquisition have complete no-key defaults.

## Market Snapshot

```text
marketsieve market refresh [--resume RUN_ID]
marketsieve market list
marketsieve market show [SNAPSHOT_ID|latest]
marketsieve market security MIC:SYMBOL [--snapshot SNAPSHOT_ID|latest]
marketsieve market compare MIC:SYMBOL... [--snapshot SNAPSHOT_ID|latest] [--fields FIELD]...
marketsieve market query [--snapshot SNAPSHOT_ID|latest] [CLASSIFICATION FILTERS] [VALUE FILTERS]
```

`refresh` is the only market command with network effects. It creates an immutable
`market-snapshot/v2` object and returns nonzero when configured coverage thresholds are not met.
`show` verifies `market-snapshot-manifest/v2` and returns market context and artifact paths.
`security` and `compare` read `market-snapshot-security/v1` records from `securities.jsonl`; they
never fetch or recalculate. `list` returns `market-snapshot-list/v1`. `query` applies OR within one
classification and AND across classifications, numeric bounds, and missingness tests, then returns
instrument-ID-sorted `market-snapshot-query-result/v1`. It does not persist a subset.

The supported Make entry point is `make market-snapshot`.

## Security research

```text
marketsieve research build MIC:SYMBOL [--snapshot SNAPSHOT_ID|latest]
marketsieve research list [--snapshot SNAPSHOT_ID] [--security MIC:SYMBOL]
marketsieve research show [RESEARCH_ID|latest] [--snapshot SNAPSHOT_ID] [--security MIC:SYMBOL]
```

`build` is the only research command with network effects. The security must resolve from the
selected verified Snapshot. It returns `security-research/v1` and stores a self-contained,
content-addressed pack. `list` and `show` verify saved objects without contacting yfinance.
`show latest` requires a security and resolves the latest exact Snapshot-security pair.

The application boundary is a typed request, typed imported result, and repository interface. It
does not depend on Click, JSON transport, MCP, or an agent. A future MCP adapter may call these same
use cases and return the same schemas; it must not become another acquisition or persistence path.

## Portfolio, watchlist, and routine reports

```text
marketsieve portfolio import PATH --broker NAME --as-of TIMESTAMP
marketsieve portfolio show
marketsieve watchlist add MIC:SYMBOL
marketsieve watchlist remove MIC:SYMBOL
marketsieve watchlist show
marketsieve --config FILE daily {jp,us}
marketsieve --config FILE weekly
marketsieve report {list,show,export}
```

Portfolio results use `portfolio-result/v3`, watchlists use `watchlist-result/v2`, and daily or
weekly reports use `decision-report/v2`. Watchlists contain explicit instruments only.

## Generic data workbench and experiments

`source`, generic `snapshot`, and `experiment` commands remain available for independent workflows.
Their providers are never fallbacks for Market Snapshot or Security Research acquisition.

## Capability and failure contract

`marketsieve capabilities --output json` returns `capabilities-result/v4`. JSON errors use stable
envelopes. Snapshot cell failures use the provider-normalized codes in `definitions.json`.
`failures.jsonl` excludes expected `not_applicable` cells.
