# MarketSieve SDK

`marketsieve` is the public, typed SDK at the center of the MarketSieve repository. It exposes
exchange-qualified instruments, exact daily OHLCV values, the `DailyBarSource` contract,
deterministic Japanese and U.S. synthetic sources, and SMA20 state-change analysis.
It also exposes time-correct SMA20 historical replay and concrete, channel-neutral replay reports.

The SDK performs no network or file I/O and does not configure logging. Synthetic observations are
fixed repository data, and analysis results are observable conditions rather than investment
recommendations.

See the [repository README](https://github.com/satter0827/marketsieve) for project status and
development instructions.
