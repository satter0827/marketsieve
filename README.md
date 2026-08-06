# MarketSieve

MarketSieve is a deterministic analysis workbench for Japanese and U.S. equities. It acquires
explicit market data, stores immutable evidence, calculates reproducible decisions and candidate
screens, and builds a static workspace that external tools such as Codex can analyze.

MarketSieve does not run a language model, send messages, place orders, or persist external research
and conversations. `buy_candidate` and other decision actions identify research states, not trade
instructions.

## Daily use

Open **Run and Debug** in VS Code and use the numbered configurations from top to bottom. First use
requires `01` through `03`. An empty portfolio and empty watchlist are valid; continue with bounded
discovery (`10` or `20`) or add a known instrument (`30`).

| Use | Terminal | VS Code launch | Network | Result |
| --- | --- | --- | --- | --- |
| Create configuration | `make setup-config` | `01 First Run: Create Configuration` | No | `marketsieve.toml` |
| Import Rakuten portfolio | `make portfolio-import BROKER=rakuten PORTFOLIO=/absolute/path.csv` | `02 First Run: Import Rakuten Portfolio` | No | immutable holdings state |
| Check readiness | `make daily-status` | `03 Daily Use: Check Readiness` | No | next-action diagnostics |
| Discover JP candidates | `make screen-refresh-jp` | `10 Discovery: Refresh JP Candidates (Network)` | Yes | universe, price snapshots, screening report |
| Discover US candidates | `make screen-refresh-us` | `20 Discovery: Refresh US Candidates (Network)` | Yes | universe, price snapshots, screening report |
| Add an instrument | `make watchlist-add INSTRUMENT=XTKS:7203` | `30 Watchlist: Add Instrument` | No | immutable watchlist revision |
| Analyze JP instruments | `make daily-jp` | `40 Daily Use: Analyze JP Watchlist (Network)` | Yes | static daily report |
| Analyze US instruments | `make daily-us` | `50 Daily Use: Analyze US Watchlist (Network)` | Yes | static daily report |
| Build weekly brief | `make weekly` | `60 Weekly Use: Build Brief` | No | static weekly report |
| Build analysis workspace | `make analysis-build` | `70 Analysis: Build Workspace` | No | `context.json`, `analysis.md` |
| Show analysis workspace | `make analysis-show` | `80 Analysis: Show Workspace` | No | verified static analysis |

Market-data credentials stay in the invoking environment. The product itself has no model-provider
cost. J-Quants, Alpha Vantage, FRED, SEC, and EDINET availability and cost depend on the selected
provider account and plan.

## External analysis

After `make analysis-build`, point Codex or another external research tool at:

```text
.marketsieve/analysis/README.md
.marketsieve/analysis/context.json
.marketsieve/analysis/analysis.md
```

`context.json` contains evidence identifiers, static decisions, screening candidates, exact previous
report deltas, missing inputs, and diagnostics. It omits position quantities, acquisition prices,
account types, local CSV paths, personal identifiers, and credentials. External news research and
the human discussion remain outside MarketSieve's canonical artifacts.

## Watchlist and screening

```shell
uv run marketsieve watchlist add XTKS:7203
uv run marketsieve watchlist add XNAS:MSFT
uv run marketsieve watchlist add XTKS:7203 --from-screen REPORT_ID
uv run marketsieve watchlist remove XTKS:7203
uv run marketsieve watchlist show

uv run marketsieve --config marketsieve.toml screen refresh jp
uv run marketsieve --config marketsieve.toml screen refresh us
uv run marketsieve --config marketsieve.toml screen update jp
uv run marketsieve --config marketsieve.toml screen run jp
```

`screen refresh` has configured acquisition, fetch, lookback, processing, and display limits. It does
not retry, switch providers, or shorten the requested range. Partial failures and rate limits remain
visible as report diagnostics. Adding a screening result to the watchlist always requires an explicit
human command.

## Static reports and Strategy Lab

```shell
uv run marketsieve report list --output json
uv run marketsieve report show latest
uv run marketsieve report export latest

uv run marketsieve experiment run strategy.toml --output json
uv run marketsieve experiment show RUN_ID --output json
uv run marketsieve experiment compare LEFT_RUN_ID RIGHT_RUN_ID --output json
```

Daily and weekly reports, screening reports, Markdown projections, and Strategy Lab runs remain
deterministic and immutable. The balanced medium-term component is a deterministic Decision Policy.

## Packages

The workspace builds independent distributions for the SDK, extension API, CLI, Rakuten importer,
and CSV, J-Quants, Alpha Vantage, FRED, SEC, and EDINET sources. The public `marketsieve` SDK has no
CLI, configuration, logging, network, database, delivery, or model-provider dependency.

```shell
make sync
make format-check
make lint
make typecheck
make test
make check
make build
```

See [documentation](docs/README.md), [formal design](docs/design/README.md), and
[contribution workflow](CONTRIBUTING.md).
