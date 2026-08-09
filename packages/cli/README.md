# marketsieve-cli

The local MarketSieve application. It owns explicit invocation inputs, optional execution settings,
yfinance composition, immutable Snapshot and Research storage, schema validation, Explorer
projections, operation history, and the five-entry CLI.

```shell
marketsieve market build --all --evidence price --history-days 1095
marketsieve market show latest
marketsieve research build XNAS:MSFT --snapshot latest --evidence price --history-days 3653
marketsieve operations artifacts doctor --output json
```

All machine schemas and Explorer renderer resources are included in this distribution. The CLI
depends on the SDK and extension packages but keeps their public interfaces independent from CLI,
settings, storage, logging, and provider implementations.
