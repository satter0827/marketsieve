# MarketSieve

MarketSieve is a local evidence workbench for Japanese and U.S. equities. It acquires data from
yfinance without an API key, publishes broad Market Snapshots and focused Security Research Packs,
and leaves interpretation to a human or an external AI.

It does not manage a portfolio or watchlist and does not produce scores, rankings, recommendations,
or model output.

## Run from a source checkout

MarketSieve supports macOS and Ubuntu with Python 3.12 through 3.14.

```shell
make sync
make doctor
make market-capture MARKET=jp
make market-capture MARKET=us
make market-show
make market-preview
```

Select an exact security from a verified Snapshot before building deeper evidence:

```shell
make market-query QUERY_ARGS='--market jp --profile swing --domain return --domain risk --order return_20d:desc --limit 30'
make research-build INSTRUMENTS='XTKS:7203'
make research-preview INSTRUMENT='XTKS:7203'
```

Every analytical scope is an invocation input. The optional `marketsieve.settings.toml` contains
only bounded execution and quality settings and can be created with `make setup-settings`.

## Install a verified release

Download all files from one GitHub Release, verify them against `SHA256SUMS`, then install the CLI
from that directory:

```shell
python -m pip install --find-links . "marketsieve-cli==VERSION"
marketsieve doctor
```

The four MarketSieve distributions come from the GitHub Release. pip resolves third-party runtime
dependencies from the configured package index. MarketSieve packages are not published to PyPI.

## Inspect saved evidence

Snapshots are stored below `.marketsieve/market-snapshots/objects/SNAPSHOT_ID/`; Research Packs are
stored below `.marketsieve/research/objects/RESEARCH_ID/`. JSON and JSONL are authoritative.
`summary.md` and `explorer.html` are deterministic views over the same files. Explorer files use
browser fetch APIs and must be opened through `market preview` or `research preview`, not directly
through `file://`.

Saved-data commands do not contact the network or recalculate observations. Diagnose current,
incompatible, corrupt, and orphan objects with:

```shell
marketsieve operations artifacts doctor --output json
```

Pre-1.0 objects are never migrated or deleted automatically. Rebuild them with the current command
contract when they are reported as incompatible.

If acquisition stops before publication, the error and failed operation record expose the same
16-character resume run ID. Resume only that saved request with
`marketsieve market build --resume TOKEN`.

The public CLI contains `market`, `research`, `operations`, `doctor`, and `capabilities`. The public
SDK contains `marketsieve.model`, `marketsieve.indicators`, and `marketsieve.fields`.

See the [documentation index](docs/README.md), [1.0 roadmap](docs/roadmap.md), and
[contribution workflow](CONTRIBUTING.md).
