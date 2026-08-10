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

## Observe acquisition

VS Code network launch entries show one stderr line for each bounded acquisition update. Every line
uses the same order: time, state, phase, completed count, total count, failure count, and elapsed
time. Retry details follow those fields. A heartbeat repeats the current phase after 15 seconds
without another event, so a quiet provider call is still visibly running.

Progress is written only when stderr is a TTY. stdout remains one final JSON document, and pipes and
CI stay quiet. The same progress is always stored in operation history. From another terminal, find
the running UUID and inspect its current state or events:

```shell
marketsieve operations run list --status running --output json
marketsieve operations run show OPERATION_RUN_ID --output json
marketsieve operations run events OPERATION_RUN_ID --output json
```

Pressing Ctrl+C records `cancelled` with exit code 130. Market acquisition prints the exact
`marketsieve market build --resume TOKEN` command for its saved request. Research keeps every Pack
published before cancellation in the operation record.

## Install a verified release

Download all files from one GitHub Release, verify them against `SHA256SUMS`, then install the CLI
from that directory:

```shell
shasum -a 256 -c SHA256SUMS
python -m pip install --find-links . "marketsieve-cli==1.0.0"
marketsieve doctor
```

The four MarketSieve distributions come from the GitHub Release. pip resolves third-party runtime
dependencies from the configured package index. All four distributions must have exactly the same
version; `doctor` reports not ready when one is missing or different. MarketSieve packages are not
published to PyPI. Linux users may run `sha256sum -c SHA256SUMS` instead of `shasum`.

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

If acquisition fails before publication, the error and failed operation record expose the same
16-character resume run ID. Resume only that saved request with
`marketsieve market build --resume TOKEN`.

The public CLI contains `market`, `research`, `operations`, `doctor`, and `capabilities`. The public
SDK contains `marketsieve.model`, `marketsieve.indicators`, and `marketsieve.fields`.
Snapshot v9, Research v9, Explorer v5, operation v2, and capabilities v13 are the current contracts.
In the 1.x line, supported public SDK and CLI behavior, settings, and current-artifact readers remain
compatible. Pre-1.0 artifacts are outside that compatibility boundary.

See the [documentation index](docs/README.md), [1.0 roadmap](docs/roadmap.md), and
[contribution workflow](CONTRIBUTING.md).
