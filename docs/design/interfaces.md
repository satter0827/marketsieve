# Interfaces

## CLI

```text
marketsieve [--settings FILE] market build
  (--all | --market jp|us... | --index INDEX...)
  --evidence DOMAIN... [--history-days DAYS]
marketsieve market build --resume RUN_ID
marketsieve market list
marketsieve market show SNAPSHOT_ID|latest
marketsieve market query --snapshot SNAPSHOT_ID|latest [FILTERS...]
marketsieve market security MIC:SYMBOL --snapshot SNAPSHOT_ID|latest
marketsieve market compare MIC:SYMBOL... --snapshot SNAPSHOT_ID|latest [--fields FIELD...]
marketsieve market diff LEFT_SNAPSHOT RIGHT_SNAPSHOT [--fields FIELD...]

marketsieve [--settings FILE] research build MIC:SYMBOL...
  --snapshot SNAPSHOT_ID|latest --evidence DOMAIN... [--history-days DAYS]
marketsieve research list [--snapshot ID] [--security MIC:SYMBOL]
marketsieve research show RESEARCH_ID|latest [--snapshot ID --security MIC:SYMBOL]

marketsieve doctor
marketsieve capabilities
```

Scope, evidence domains, history, instruments, Snapshot identity, query filters, and comparison
fields are invocation inputs. They are never read from settings. `[yfinance]`, `[quality.market]`,
and `[quality.research]` are the only settings tables.

`market query`, `security`, `compare`, and `diff` read verified stored objects. They do not acquire,
recalculate, or save subsets. Repeated classification values are OR; different classifications and
numeric constraints are AND. Numeric constraints accept only fields defined as numeric.

## Documents

Current top-level contracts are `market-snapshot/v3`, `market-snapshot-list/v2`,
`market-snapshot-diff/v1`, `security-research/v2`, `security-research-list/v2`, and
`security-research-batch/v1`. Stable JSON keys and formal schemas are English. Human CLI output may
be localized without changing machine documents.
