# Interfaces

## Root command

`marketsieve` analyzes exchange-qualified Japanese and U.S. equities. Global options select
non-secret configuration, locale, output mode, and optional local logging. Machine output uses
versioned English-keyed JSON.

## Portfolio and watchlist

```shell
marketsieve portfolio import PATH --broker canonical --as-of TIMESTAMP
marketsieve portfolio import PATH --broker rakuten --as-of TIMESTAMP
marketsieve portfolio show

marketsieve watchlist add XTKS:7203
marketsieve watchlist add XNAS:MSFT
marketsieve watchlist add XTKS:7203 --from-screen REPORT_ID
marketsieve watchlist remove XTKS:7203
marketsieve watchlist show
```

Canonical portfolio CSV uses
`mic,symbol,currency,timezone,quantity,average_acquisition_price,account_type` and contains holdings
only. `portfolio-result/v3` contains immutable source identity, diagnostics, and holdings. Watchlist
revisions use `watchlist-result/v1` and infer currency and timezone only from supported MICs XTKS,
XNAS, and XNYS.

Rakuten import accepts CP932 twelve-column `assetbalance(all)` exports only when every security
category is zero and the detail section explicitly contains no holding. Cash values may be nonzero
because they do not assert a security position.

## Screening

```shell
marketsieve --config marketsieve.toml screen update {jp,us}
marketsieve --config marketsieve.toml screen run {jp,us} [--as-of TIMESTAMP]
marketsieve --config marketsieve.toml screen refresh {jp,us}
marketsieve screen show {ID,latest} [--market {jp,us}]
```

`update` performs only configured universe import or fetch. `run` consumes verified local daily-bar
snapshots and performs no network access. `refresh` validates source compatibility, updates the
universe, fetches at most `fetch_limit` instruments for `lookback_days`, and runs the same offline
screen. The refresh knowledge time is fixed after universe and price acquisition. Refresh exposes
no historical-time option; an explicit historical evaluation uses `screen update` followed by
`screen run --as-of`. `eligible_mics` is part of the universe request,
so excluded instruments consume neither `acquisition_limit` nor `fetch_limit`. Partial failures and
excluded MICs remain diagnostics in `screening-report/v1`.

## Routine reports

```shell
marketsieve --config marketsieve.toml daily {jp,us} [--as-of TIMESTAMP]
marketsieve --config marketsieve.toml weekly [--as-of TIMESTAMP]
marketsieve report list
marketsieve report show {ID,latest}
marketsieve report export {ID,latest} --format markdown
```

Daily analysis composes the latest holdings and watchlist. It acquires configured evidence for the
selected market and writes immutable `decision-report/v1` JSON plus deterministic Markdown. Weekly
analysis reads eligible JP and US reports and screening reports without acquisition or recalculation.

## Analysis workspace

```shell
marketsieve analysis build
marketsieve analysis show
```

`build` writes `.marketsieve/analysis/README.md`, `context.json`, and `analysis.md`. `show` verifies
the context ID, canonical JSON, README, and Markdown before displaying the current view. JSON output
uses `analysis-context/v1`.

## Data workbench

```shell
marketsieve source list
marketsieve source import PATH --plugin csv
marketsieve source doctor PROFILE --kind daily_bars
marketsieve source fetch PROFILE MIC:SYMBOL --start DATE --end DATE --kind daily_bars
marketsieve snapshot list
marketsieve snapshot show OBJECT_ID
marketsieve snapshot verify OBJECT_ID
marketsieve inspect MIC:SYMBOL --source-profile PROFILE
marketsieve compare MIC:SYMBOL MIC:SYMBOL --source-profile PROFILE
marketsieve analyze sma MIC:SYMBOL --source-profile PROFILE
```

Acquisition commands are explicit. Inspection, comparison, indicator calculation, snapshot reads,
report reads, and workspace reads are offline.

## Strategy Lab

```shell
marketsieve experiment run SPEC.toml
marketsieve experiment show RUN_ID
marketsieve experiment compare LEFT_RUN_ID RIGHT_RUN_ID
```

Strategy Lab consumes explicit verified snapshot IDs. It stores immutable deterministic runs and
compares metrics without declaring automatic profit, a winner, or statistical superiority.

## Capability and failure contract

`marketsieve capabilities --output json` enumerates every command, option, schema, network effect,
secret use, and optional write. Unknown fields and unsupported schema major versions are rejected.
User errors contain a stable code and recovery text without a traceback or secret value.
