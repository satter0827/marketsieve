# marketsieve-cli

Public command-line workbench for deterministic Japanese and U.S. equity analysis.

```shell
marketsieve portfolio import holdings.csv --broker canonical --as-of 2026-08-06T12:00:00+09:00
marketsieve watchlist add XTKS:7203
marketsieve --config marketsieve.toml screen refresh jp
marketsieve --config marketsieve.toml daily jp
marketsieve analysis build
marketsieve analysis show
```

The CLI owns configuration, explicit source selection, local persistence, static projections, and
console output. It composes the public SDK and extension packages without moving I/O concerns into
the SDK. It does not execute a model, send messages, or place orders.
