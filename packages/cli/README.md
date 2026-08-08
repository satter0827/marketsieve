# marketsieve-cli

Public command-line workbench for reproducible Japanese and U.S. equity analysis.

```shell
marketsieve market refresh
marketsieve market show latest
marketsieve market query --market jp --present close --fields close
marketsieve market security XTKS:7203
marketsieve research build XTKS:7203
marketsieve research show latest --security XTKS:7203
```

The CLI owns configuration, source selection, local persistence, static projections, and console
output. Market Snapshot and Security Research acquisition use yfinance without registration or an
API key. JSONL is authoritative; CSV and self-contained HTML are views; Excel is unsupported.

Application services use typed protocols independent from Click and transport details, so a future
MCP adapter can reuse the same behavior. The CLI does not execute a model, send messages, rank
securities, make trading recommendations, or place orders.
