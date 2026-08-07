# Operations

## Supported matrix operation

The normal broad-market workflow is:

```shell
make sync
make market-matrix
uv run marketsieve matrix show latest
uv run marketsieve matrix list
uv run marketsieve matrix query --market jp --present close --fields close
```

No account, API key, or provider environment variable is required. The optional `[matrix]` table
controls selected indices, history length, price batch size, company-information concurrency,
timeout, retry policy, and coverage thresholds. Defaults are three years, batches of 50, two profile
workers, 30 seconds, three attempts, two-second base backoff, 95% overall coverage, and 90% per
index.

Network failures, rate limits, unavailable financial statements, and insufficient history remain in
the row-level missing map and `failures.jsonl`. Operators may resume only a run whose request
fingerprint matches. They may adjust yfinance symbols, batching, waits, or retries when coverage is
low; another provider is not an allowed recovery.

## Generated state

Project-local caches, runs, matrices, reports, watchlists, snapshots, coverage, logs, and review
evidence stay below `.marketsieve`. Immutable matrices are stored at
`.marketsieve/matrices/objects/MATRIX_ID`. Decision reports and watchlists for the current schemas
are stored below `.marketsieve/reports/v2` and `.marketsieve/watchlists/v2`. Matrix objects contain
all files needed for handoff and do not refer to a separate analysis workspace.

Live matrix objects and analyses contain redistributable-provider-derived values and are local
operational artifacts. They are not committed. yfinance use is limited to personal local research in
accordance with its stated intended use.

## Reading and comparing

`matrix list`, `matrix query`, `matrix row`, and `matrix compare` are offline views over the
authoritative JSONL. Use an explicit matrix ID for a reproducible historical cross-section. Use `fields.json`
to interpret names, units, formulas, periods, and missingness. Use `overview.html` for local search,
sorting, and classification filtering; it has no external CDN or runtime data request.

## Other operations

`make setup-config`, portfolio import, watchlist maintenance, daily analysis, weekly reporting, and
experiment replay remain supported. They do not mutate or substitute the market matrix. Daily
provider credentials remain in the invoking environment and are unrelated to yfinance matrix use.

## Development and review

Run focused tests while editing and the shared gates before handoff:

```shell
make format-check
make lint
make typecheck
make test
make check
make build
```

The review SHA is frozen before CI. Generated review evidence is stored below `.marketsieve` and is
not a substitute for the tested source contract.
