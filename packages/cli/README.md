# marketsieve-cli

Public command-line workbench for reproducible Japanese and U.S. equity analysis.

```shell
marketsieve matrix refresh
marketsieve matrix show latest
marketsieve matrix row XTKS:7203
marketsieve matrix compare XTKS:7203 XNAS:MSFT --fields return_252d
marketsieve analysis build
```

The CLI owns configuration, explicit source selection, local persistence, static projections, and
console output. The broad matrix uses yfinance without registration or an API key. JSONL is
authoritative; CSV and self-contained HTML are views; Excel output is unsupported.

The CLI composes the public SDK and extension packages without moving I/O concerns into the SDK. It
does not execute a model, send messages, rank securities, make trading recommendations, or place
orders.
