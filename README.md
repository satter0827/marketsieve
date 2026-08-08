# MarketSieve

MarketSieve is a reproducible analysis workbench for Japanese and U.S. equities. A Market Snapshot
captures the Nikkei 225, TOPIX 500, S&P 500, Dow 30, and Nasdaq-100 as one broad, immutable market
cross-section. A Security Research Pack adds deeper evidence for one Snapshot security when needed.

Runtime market and research data comes only from yfinance. It requires no account, API key, or environment
variable. MarketSieve never fills a missing value from another source: every absent cell retains a
stable reason code. It produces no score, ranking, trade recommendation, order, message, or Excel
file.

## Market Snapshot and security research

```shell
make sync
make market-snapshot
uv run marketsieve market show latest
uv run marketsieve market list
uv run marketsieve market query --market jp --present close --fields close --fields return_252d
uv run marketsieve market security XTKS:7203
make security-research INSTRUMENT=XTKS:7203
uv run marketsieve research show latest --security XTKS:7203
```

`make market-snapshot` downloads three years of adjusted daily prices in batches and collects company
and financial data with bounded concurrency. The built-in index assets define membership and
provenance; they are not a second runtime market-data source.

Each immutable Snapshot is stored below
`.marketsieve/market-snapshots/objects/SNAPSHOT_ID/`:

- `README.md` explains the dataset without requiring outside context.
- `securities.jsonl` is the authoritative one-row-per-security dataset.
- `definitions.json` defines every field and stable missing-value code.
- `market.json`, `segments.jsonl`, `quality.json`, and `failures.jsonl` preserve market context and quality.
- `securities.csv`, self-contained `explorer.html`, and `summary.md` are deterministic views.

`market list`, `market query`, `market security`, and `market compare` read only saved objects. They
do not use the network, recalculate indicators, or create subsets. A historical cross-section is
selected by its Snapshot ID.

`research build` accepts only a security present in the selected Snapshot. It stores up to ten years
of adjusted daily history, retrieval-time company facts, annual and quarterly statements, dividends,
splits, earnings events, exact failures, and the matching market, index, sector, and industry context
below `.marketsieve/research/objects/RESEARCH_ID/`. The pack contains no score, recommendation, AI
prompt, or prescribed analysis order. Its versioned JSON/JSONL boundary can later be exposed through
MCP without changing acquisition or persistence.

## Other supported workflows

Use `make daily-status` to validate configuration and local routine-analysis readiness.

| Use | Terminal | VS Code launch | Network | Result |
| --- | --- | --- | --- | --- |
| Show latest market | `make market-show` | `01 Market: Show Latest Snapshot` | No | verified Snapshot paths |
| Refresh broad market | `make market-snapshot` | `02 Market: Refresh Snapshot (Network)` | Yes | immutable Market Snapshot |
| Query one market | `make market-query MARKET=jp` | `03 Market: Query Snapshot` | No | filtered JSON result |
| Research one security | `make security-research INSTRUMENT=XTKS:7203` | `04 Research: Build Security Pack (Network)` | Yes | immutable Research Pack |
| Show latest research | `make research-show INSTRUMENT=XTKS:7203` | `05 Research: Show Latest Security Pack` | No | verified Research Pack paths |

The generic source, snapshot, portfolio, watchlist, daily/weekly, and experiment capabilities remain
available because they serve reproducible workflows outside broad-market Snapshot generation.

## Scope and data use

yfinance describes its service as intended for research, education, and personal use. MarketSieve's
generated market artifacts are therefore for personal local analysis. Provider responses may be
partial or rate-limited; MarketSieve records that state instead of substituting a provider or
inventing a value.

The public `marketsieve` SDK remains independent from the CLI, configuration, network clients,
storage, delivery, and model providers. The workspace builds separate distributions for the SDK,
extension API, CLI, Rakuten importer, and source adapters including `marketsieve-source-yfinance`.

```shell
make format-check
make lint
make typecheck
make test
make check
make build
```

See [documentation](docs/README.md), [formal design](docs/design/README.md), and the
[contribution workflow](CONTRIBUTING.md).
