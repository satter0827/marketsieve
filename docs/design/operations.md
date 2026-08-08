# Operations

Run `make sync` once and `make doctor` after environment changes. Normal operation is
`make market-capture MARKET=jp` and `make market-capture MARKET=us` after their respective closes,
followed by `make market-preview` or `make market-query`. Build focused evidence
with `make research-build INSTRUMENTS='MIC:SYMBOL ...'` only after selecting a Snapshot.

`make market-build` remains the explicit combined-scope acquisition command. Direct CLI arguments select one
market, one or more indices, narrower evidence domains, and different history lengths. Optional
settings are created with `make setup-settings`; analytical scope never persists there.

`make market-reconstruct MARKET=jp AS_OF=YYYY-MM-DD` creates price-only historical evidence. It
rejects future dates and dates before the selected built-in universe assets. It never reconstructs
company or financial facts. Capture is one-shot and suitable for a future external scheduler, but
MarketSieve does not install cron jobs, run a daemon, or send notifications.

Completed objects live below `.marketsieve/market-snapshots/objects` and
`.marketsieve/research/objects`. Runs and caches are separate. Completed valid objects are retained
as historical observations. Local live evidence is gitignored and must not be committed.

VS Code launch entries cover JP and US Capture, Snapshot preview and swing exploration, and Research
build and preview. Tasks expose granular market, reconstruction, research,
and developer actions. `.marketsieve` is visible in the Explorer but excluded from file watching.
