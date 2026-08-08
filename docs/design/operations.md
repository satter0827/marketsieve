# Operations

## Broad-to-deep workflow

```shell
make sync
make market-snapshot
uv run marketsieve market show latest
uv run marketsieve market query --market jp --present close --fields close
make security-research INSTRUMENT=XTKS:7203
uv run marketsieve research show latest --security XTKS:7203
```

No account, API key, or provider environment variable is required. `[market]` controls indices,
three-year history, batching, profile concurrency, timeout, retries, and coverage thresholds.
`[research]` controls ten-year history, minimum price observations, timeout, and retries.

Network failures, rate limits, unavailable statements, and insufficient history remain explicit.
Operators may adjust yfinance symbols, batching, waits, or retries. Another provider is not an
allowed automatic recovery.

## Generated state

All local state stays below `.marketsieve`. Market Snapshots live at
`.marketsieve/market-snapshots/objects/SNAPSHOT_ID`; transient runs live beside them under `runs`.
Security Research Packs live at `.marketsieve/research/objects/RESEARCH_ID`. Decision reports and
watchlists retain their existing `reports/v2` and `watchlists/v2` roots.

Market and research objects are immutable, self-contained handoff directories. Live provider data
is not committed. yfinance use is limited to personal local research.

## Reading evidence

Use an exact Snapshot ID for a reproducible historical cross-section. `securities.jsonl` is the
security authority, `definitions.json` explains fields and missing values, `market.json` and
`segments.jsonl` provide aggregate context, and `explorer.html` is an offline browser view.

Start broad analysis with the Snapshot. Build a Research Pack only after selecting a Snapshot
security. Read `market-context.json` before comparing the security with its market, index, sector,
or industry. Company and financial values without provider publication timestamps are marked as
retrieval-time knowledge and must not be treated as a historical point-in-time reconstruction.

## Other operations

Portfolio import, watchlist maintenance, daily analysis, weekly reporting, generic snapshots, and
experiments remain independent. They do not mutate or substitute Market Snapshot or Security
Research objects.

## Development and review

```shell
make format-check
make lint
make typecheck
make test
make check
make build
```

The review SHA is frozen before CI. Review evidence stays below `.marketsieve` and does not replace
the tested source contract.
