# Operations

## Supported current operation

MarketSieve supports one-shot local analysis, immutable storage, public distribution builds, and
explicit market-data acquisition on Python 3.12 through 3.14. Python 3.13 is the primary development
version.

```shell
make sync
make doctor
make capabilities-json
make build
```

Project-local caches, logs, generated evidence, reports, watchlists, screening state, and analysis
workspace files live below `.marketsieve`. The repository does not load `.env` files. Credentials
enter through provider-specific environment variables and are never copied into configuration,
artifacts, logs, or subprocess metadata.

## First use and empty state

```shell
make setup-config
make portfolio-import BROKER=rakuten PORTFOLIO=/absolute/path.csv
make daily-status
```

Configuration creation never overwrites an existing file. Portfolio import retains normalized
values and a source digest, not the input path or bytes. An empty holdings state and empty watchlist
are valid. Readiness directs the user to candidate discovery or explicit watchlist entry instead of
requesting another import.

## Discovery and watchlist

```shell
make screen-refresh-jp
make screen-refresh-us
make watchlist-add INSTRUMENT=XTKS:7203
make watchlist-add INSTRUMENT=XTKS:7203 SCREEN_REPORT=REPORT_ID
make watchlist-show
```

`screen refresh` performs configured universe acquisition, bounded daily-bar acquisition, and
deterministic screening. Each market configures `acquisition_limit`, `fetch_limit`, `lookback_days`,
`processing_limit`, and `display_limit`. The operation does not retry, switch providers, shorten a
range, or present the universe prefix as a rank. Missing data, rate limits, and partial failures
remain in the static report. The universe source applies `eligible_mics` before
`acquisition_limit`. Refresh uses its post-acquisition knowledge time and exposes no historical-time
option.

Adding a candidate is always a separate human action. The watchlist revision records the exact
screening report when `SCREEN_REPORT` is supplied. Supplying provenance for an existing item creates
an explicit `add_provenance` revision instead of silently ignoring or overwriting history. Removing
an instrument creates another immutable revision.

## Daily and weekly reports

```shell
make daily-jp
make daily-us
make weekly
```

Daily commands acquire evidence only for the selected market's holdings and watchlist instruments.
Price failure produces an indeterminate decision; optional financial and event failure lowers
available evidence and remains diagnostic. A report with only indeterminate decisions remains
inspectable but does not advance the latest usable reference.

Weekly operation is offline. It requires eligible JP and US daily references, retains their exact
IDs, and includes current screening candidates separately from portfolio decisions.

## Static analysis workspace

```shell
make analysis-build
make analysis-show
make analysis-demo
```

`analysis-build` projects verified local artifacts into deterministic `context.json` and
`analysis.md`. Existing decision and screening objects remain unchanged. `analysis-show` verifies
the projection before reading it. External tools may research current sources and discuss the
result with a person, but MarketSieve does not store that research or conversation.

The analysis context intentionally omits position quantities, acquisition prices, account types,
portfolio file paths, personal identifiers, and credentials. Generated workspaces are local state
and are never committed.

## VS Code operation

Run and Debug is the primary human entry point. Configurations `01` through `03` establish local
state, `10` and `20` discover candidates, `30` edits the watchlist, `40` and `50` run daily analysis,
`60` builds the weekly brief, and `70` and `80` build and read the analysis workspace. Configurations
`90` through `92` are representative code-debug entry points.

Tasks provide grouped First Run, Discovery, Daily, Analysis, and Developer operations. Every normal
operation delegates to a Make target; command behavior is not duplicated in editor JSON.

## Development and review

```shell
make format-check
make lint
make typecheck
make test
make check
make evidence
```

After local evidence, review the final diff against `origin/develop`, fix findings as one batch,
rerun the gate, commit, and attest that exact clean SHA. A code change after CI begins returns to the
pre-PR review sequence.

## Unsupported operation

MarketSieve does not run models, send messages, place orders, automate a browser or brokerage,
perform background scheduling, merge providers, or generate opaque investment scores. The SEC
`SEC_USER_AGENT` contact value remains a source-specific fair-access header and is not a messaging
feature.
