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
  [--budget VALUE --budget-currency JPY|USD --trading-unit COUNT --use-snapshot-fx]
marketsieve market security MIC:SYMBOL --snapshot SNAPSHOT_ID|latest
marketsieve market compare MIC:SYMBOL... --snapshot SNAPSHOT_ID|latest [--fields FIELD...]
marketsieve market diff LEFT_SNAPSHOT RIGHT_SNAPSHOT [--fields FIELD...]
marketsieve market preview SNAPSHOT_ID|latest [--port PORT] [--open]

marketsieve [--settings FILE] research build MIC:SYMBOL...
  --snapshot SNAPSHOT_ID|latest --evidence DOMAIN... [--history-days DAYS]
marketsieve research list [--snapshot ID] [--security MIC:SYMBOL]
marketsieve research show RESEARCH_ID|latest [--snapshot ID --security MIC:SYMBOL]
marketsieve research preview RESEARCH_ID [--port PORT] [--open]
marketsieve research preview latest --security MIC:SYMBOL [--port PORT] [--open]
marketsieve operations artifacts doctor
marketsieve operations artifacts list [--type snapshot|research] [--status STATUS]
marketsieve operations run list [--status STATUS] [--command COMMAND]
marketsieve operations run show RUN_ID
marketsieve operations run events RUN_ID [--level LEVEL]
marketsieve operations run prune RUN_ID... [--apply]
marketsieve operations run prune --before YYYY-MM-DD [--status STATUS] [--apply]

marketsieve doctor
marketsieve capabilities
```

The public CLI has exactly five top-level entries: `market`, `research`, `operations`, `doctor`,
and `capabilities`. Preview belongs to its evidence workflow; artifact inventory and run history
belong to `operations`.

Scope, evidence domains, history, instruments, Snapshot identity, query filters, and comparison
fields are invocation inputs. They are never read from settings. `[yfinance]`, `[quality.market]`,
and `[quality.research]` are the only settings tables.

`market query`, `security`, `compare`, and `diff` read verified stored objects. They do not acquire,
recalculate, or save subsets. Repeated classification values are OR; different classifications and
numeric constraints are AND. Numeric constraints accept only fields defined as numeric.
Purpose profiles affect stored-data selection only and never alter Snapshot acquisition. Budget and
trading-unit projections are invocation-only and are not persisted. Ordering is neutral and does
not produce a score or recommendation.

`EquityBatchFetcher`, `MarketIndicatorFetcher`, and `SecurityResearchFetcher` accept an optional
keyword-only `ProgressSink`. `AcquisitionProgress` always carries phase, state, completed, total,
and failure count. Retrying progress additionally carries attempt, maximum attempts, and bounded
wait seconds. Counts are validated at construction. A sink is an observation channel: it is not
part of a request, response hash, Snapshot identity, or Research identity.

Network acquisition writes line-oriented progress only to TTY stderr. The stable field order is
time, state, phase, completed, total, failures, and elapsed time, followed by retry fields when
present. stdout contains only the final command document. Non-TTY execution, pipes, and CI do not
render progress but still persist operation events. Stored-data query, show, compare, and preview
commands have no acquisition progress path.

`preview` binds to `127.0.0.1`, selects an available port by default, and exposes only the selected
verified object's manifest-registered files. It disables directory listing, path traversal,
symlinks, and access outside the object.

## Documents

Current top-level contracts are `market-snapshot/v9`, `market-snapshot-list/v3`,
`market-snapshot-query-result/v3`, `market-snapshot-comparison/v3`, `market-snapshot-diff/v1`,
`security-research/v9`, `security-research-list/v3`, `security-research-batch/v1`,
`explorer-data/v5`, `operation-run/v2`, and `capabilities-result/v12`. Every emitted record schema is
registered and packaged in `marketsieve-cli`. Stable JSON keys and formal schemas are English.
Human CLI output and Explorer labels may be localized without changing machine documents.

`--output json` never translates keys or enum values. Non-TTY `--output auto` resolves to JSON;
Rich output is used only for a TTY, and plain text requires `--output text`.
