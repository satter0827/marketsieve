# Interfaces

## Root command

`marketsieve` uses exchange-qualified `MIC:SYMBOL` identifiers. JSON output uses versioned schemas;
human output is a projection. Global configuration is optional for the matrix because defaults are
complete and yfinance needs no credentials.

## Market matrix

```text
marketsieve matrix refresh [--resume RUN_ID]
marketsieve matrix list
marketsieve matrix show [MATRIX_ID|latest]
marketsieve matrix row MIC:SYMBOL [--matrix MATRIX_ID|latest]
marketsieve matrix compare MIC:SYMBOL... [--matrix MATRIX_ID|latest] [--fields FIELD]...
marketsieve matrix query [--matrix MATRIX_ID|latest] [CLASSIFICATION FILTERS] [VALUE FILTERS]
```

`refresh` is the only matrix command with network effects. It creates an immutable
`market-matrix/v2` object and returns nonzero when configured coverage thresholds are not met.
`show` verifies the stored `market-matrix-manifest/v2` object and returns its
`market-matrix/v2` projection with summary and artifact paths. `row` returns one
`market-matrix-row/v1` with the resolved immutable matrix ID; `compare` returns one
`market-matrix-comparison/v1`. The latter two read `market-matrix-security/v1` records from
`securities.jsonl` only and never fetch or recalculate. `list` returns verified history as
`market-matrix-list/v1`. `query` applies OR within one classification and AND across classifications,
numeric bounds, and missingness tests, then returns instrument-ID-sorted `matrix-query-result/v1`.
It does not persist a subset.

The supported Make entry point is:

```text
make market-matrix
```

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
weekly canonical reports use `decision-report/v2`. Watchlist revisions record explicit instruments
only and contain no candidate-discovery provenance.

## Generic data workbench and experiments

`source`, `snapshot`, and `experiment` commands remain available for explicit non-matrix data and
policy workflows. Their source selection is never used as a fallback for matrix acquisition.

## Capability and failure contract

`marketsieve capabilities --output json` returns `capabilities-result/v3`. Operational failures use
stable JSON error envelopes when JSON output is selected. Matrix cell failures additionally use the
fixed provider-normalized codes documented by `missing-reasons.json`. `failures.jsonl` excludes
expected `not_applicable` cells.
