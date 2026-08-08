# Operations

Run `make sync` once and `make doctor` after environment changes. Normal operation is
`make market-build`, followed by `make market-show` or `make market-query`. Build focused evidence
with `make research-build INSTRUMENTS='MIC:SYMBOL ...'` only after selecting a Snapshot.

The Make defaults provide a convenient full-market run, while direct CLI arguments can select one
market, one or more indices, narrower evidence domains, and different history lengths. Optional
settings are created with `make setup-settings`; analytical scope never persists there.

Completed objects live below `.marketsieve/market-snapshots/objects` and
`.marketsieve/research/objects`. Runs and caches are separate. Completed valid objects are retained
as historical observations. Local live evidence is gitignored and must not be committed.

VS Code launch entries cover the five common operations. Tasks expose granular market, research,
and developer actions. `.marketsieve` is visible in the Explorer but excluded from file watching.
