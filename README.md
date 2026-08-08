# MarketSieve

MarketSieve builds reproducible Japanese and U.S. equity evidence from yfinance without an API key.
It separates broad Market Snapshots from on-demand Security Research and leaves interpretation to a
human or external AI.

```shell
make sync
make doctor
make market-capture MARKET=jp
make market-capture MARKET=us
make market-preview
make market-query QUERY_ARGS='--market jp --profile swing --domain return --domain risk --order return_20d:desc --limit 30'
make research-build INSTRUMENTS='XTKS:7203 XNAS:MSFT'
```

Every network run receives its analytical scope through CLI arguments. Optional
`marketsieve.settings.toml` contains only bounded runtime and quality settings; create it with
`make setup-settings` when defaults are not sufficient.

Snapshots are stored under `.marketsieve/market-snapshots/objects/SNAPSHOT_ID/`. The authoritative
files are JSON and JSONL. `explorer-data.json` is the chart-neutral deterministic projection;
`summary.md` and the self-contained `explorer.html` are human views.
Research packs are stored under `.marketsieve/research/objects/RESEARCH_ID/` and remain tied to the
source Snapshot. No Excel or CSV artifact is generated.

The public CLI is intentionally small: `market`, `research`, `doctor`, and `capabilities`. Portfolio,
watchlist, routine report, generic source, generic snapshot, and experiment workflows are not part
of the product.

See [the design index](docs/design/README.md) and [contribution workflow](CONTRIBUTING.md).
