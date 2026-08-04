# MarketSieve SDK

`marketsieve` is the public, typed SDK at the center of the MarketSieve repository. It exposes
exchange-qualified instruments, exact daily OHLCV values, the `DailyBarSource` contract,
deterministic Japanese and U.S. synthetic sources, and generic SMA, EMA, RSI, MACD, ATR, period
return, and maximum-drawdown results with reproducible evidence. The transitional historical
report uses the same generic SMA engine.

The SDK performs no network or file I/O and does not configure logging. Synthetic observations are
fixed repository data, and analysis results are observable conditions rather than investment
recommendations.

See the [repository README](https://github.com/satter0827/marketsieve) for project status and
development instructions.
