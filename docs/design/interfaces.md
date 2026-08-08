# Interfaces

## CLI

```text
marketsieve [--settings FILE] market build
  (--all | --market jp|us... | --index INDEX...)
  --evidence DOMAIN... [--history-days DAYS]
marketsieve market build --resume RUN_ID
marketsieve market capture --market jp|us --session close --evidence DOMAIN...
  --history-days DAYS [--resume RUN_ID]
marketsieve market reconstruct --market jp|us --date YYYY-MM-DD --history-days DAYS
marketsieve market list
marketsieve market show SNAPSHOT_ID|latest
marketsieve market query --snapshot SNAPSHOT_ID|latest [FILTERS...]
  [--profile short-swing|swing|position] [--domain DOMAIN...]
  [--order FIELD:asc|desc...] [--limit COUNT]
  [--budget VALUE --budget-currency ISO --trading-unit COUNT]
marketsieve market security MIC:SYMBOL --snapshot SNAPSHOT_ID|latest
marketsieve market compare MIC:SYMBOL... --snapshot SNAPSHOT_ID|latest [--fields FIELD...]
marketsieve market diff LEFT_SNAPSHOT RIGHT_SNAPSHOT [--fields FIELD...]
marketsieve market serve SNAPSHOT_ID|latest [--port PORT] [--open]

marketsieve [--settings FILE] research build MIC:SYMBOL...
  --snapshot SNAPSHOT_ID|latest --evidence DOMAIN... [--history-days DAYS]
marketsieve research list [--snapshot ID] [--security MIC:SYMBOL]
marketsieve research show RESEARCH_ID|latest [--snapshot ID --security MIC:SYMBOL]
marketsieve research serve RESEARCH_ID|latest [--snapshot ID --security MIC:SYMBOL]
  [--port PORT] [--open]

marketsieve doctor
marketsieve capabilities
```

Scope, evidence domains, history, instruments, Snapshot identity, query filters, and comparison
fields are invocation inputs. They are never read from settings. `[yfinance]`, `[quality.market]`,
and `[quality.research]` are the only settings tables.

`market query`, `security`, `compare`, and `diff` read verified stored objects. They do not acquire,
recalculate, or save subsets. Repeated classification values are OR; different classifications and
numeric constraints are AND. Numeric constraints accept only fields defined as numeric.
Purpose profiles affect stored-data selection only and never alter Snapshot acquisition. Budget and
trading-unit projections are invocation-only and are not persisted. Ordering is neutral and does
not produce a score or recommendation.

`serve` binds to `127.0.0.1`, selects an available port by default, exposes only one verified
object's Explorer files, and disables directory listing and path traversal.

## Documents

Current top-level contracts are `market-snapshot/v6`, `market-snapshot-list/v2`,
`market-snapshot-query-result/v2`, `market-snapshot-comparison/v2`, `market-snapshot-diff/v1`,
`security-research/v4`, `security-research-list/v2`, `security-research-batch/v1`, and
`capabilities-result/v8`. Capture state uses `capture-run/v1`. Stable JSON keys and formal schemas
are English. Human CLI output and Explorer labels may be localized without changing machine
documents.
