# MarketSieve SDK

`marketsieve` is the public, typed SDK at the center of the MarketSieve repository. It exposes
exchange-qualified instruments, exact daily OHLCV values, the `DailyBarSource` contract,
deterministic Japanese and U.S. synthetic sources, and generic SMA, EMA, RSI, MACD, ATR, period
return, and maximum-drawdown results with reproducible evidence. It also exposes brokerage-neutral
portfolio values, immutable decision-report values, the `DecisionPolicy` contract, and the
transparent balanced medium-term policy.

The SDK performs no network or file I/O and does not configure logging. Synthetic observations are
fixed repository data. A policy decision records evidence and a review action; it is never an order.

See the [repository README](https://github.com/satter0827/marketsieve) for project status and
development instructions.
