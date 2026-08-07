# MarketSieve

MarketSieve is a reproducible analysis workbench for Japanese and U.S. equities. Its primary market
view is one broad matrix: one security per row and one stable field per column across the Nikkei
225, TOPIX 500, S&P 500, Dow 30, and Nasdaq-100.

Runtime matrix data comes only from yfinance. It requires no account, API key, or environment
variable. MarketSieve never fills a missing value from another source: every absent cell retains a
stable reason code. It produces no score, ranking, trade recommendation, order, message, or Excel
file.

## Market matrix

```shell
make sync
make market-matrix
uv run marketsieve matrix show latest
uv run marketsieve matrix row XTKS:7203
uv run marketsieve matrix compare XTKS:7203 XNAS:MSFT --fields return_252d --fields volatility_252d
make analysis-build
```

`make market-matrix` downloads three years of adjusted daily prices in batches and collects company
and financial data with bounded concurrency. The built-in index assets define membership and
provenance; they are not a second runtime market-data source.

Each immutable object is stored below `.marketsieve/matrices/objects/MATRIX_ID/`:

- `securities.jsonl` is the authoritative one-row-per-security dataset.
- `fields.json` defines every field, formula, unit, period, source, and definition version.
- `manifest.json`, `index-summary.json`, and `failures.jsonl` preserve provenance and quality.
- `matrix.csv` and self-contained `overview.html` are deterministic views of the JSONL authority.
- `analysis.md` describes market breadth, distributions, risk, liquidity, fundamentals,
  concentration, sectors, and missingness without naming preferred securities.

`matrix row` and `matrix compare` read only the stored JSONL. They do not use the network or
recalculate indicators. `analysis build` writes `analysis-context/v2`, which references the selected
matrix instead of copying its rows.

## Other supported workflows

| Use | Terminal | VS Code launch | Network | Result |
| --- | --- | --- | --- | --- |
| Create configuration | `make setup-config` | `01 First Run: Create Configuration` | No | `marketsieve.toml` |
| Import Rakuten portfolio | `make portfolio-import BROKER=rakuten PORTFOLIO=/absolute/path.csv` | `02 First Run: Import Rakuten Portfolio` | No | immutable holdings state |
| Check readiness | `make daily-status` | `03 Daily Use: Check Readiness` | No | next-action diagnostics |
| Refresh broad matrix | `make market-matrix` | `10 Market Matrix: Refresh All Indices (Network)` | Yes | immutable matrix and analysis |
| Add an instrument | `make watchlist-add INSTRUMENT=XTKS:7203` | `30 Watchlist: Add Instrument` | No | immutable watchlist revision |
| Analyze JP instruments | `make daily-jp` | `40 Daily Use: Analyze JP Watchlist (Network)` | Yes | static daily report |
| Analyze US instruments | `make daily-us` | `50 Daily Use: Analyze US Watchlist (Network)` | Yes | static daily report |
| Build weekly brief | `make weekly` | `60 Weekly Use: Build Brief` | No | static weekly report |
| Build AI context | `make analysis-build` | `70 Analysis: Build Workspace` | No | `context.json`, `analysis.md` |

The generic source, snapshot, portfolio, watchlist, daily/weekly, and experiment capabilities remain
available because they serve reproducible workflows outside broad-universe matrix generation.

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
