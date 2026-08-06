# Quality

## Domain acceptance

Reference tests cover Japanese and U.S. exchange identity, knowledge-time filtering, deterministic
indicators, financial-history compatibility, held and unheld decision branches, candidate ordering,
and exact previous-report comparison. Decimal behavior is independent from ambient context.

## Repository acceptance

The public SDK has no dependency on CLI, configuration, logging, network, persistence, broker, or
external analysis infrastructure. Import Linter, AST boundary tests, explicit package manifests,
and isolated wheel installation enforce that boundary. Every public distribution shares one minor
release series.

## Portfolio and watchlist acceptance

Tests cover canonical holding import, anonymous real-form Rakuten empty import, invalid encoding,
contradictory balances, unsupported non-empty details, unknown sections, source-byte non-retention,
atomic storage, tamper detection, and schema validation.

Watchlist tests cover supported MIC metadata, add, remove, no-op duplicate add, provenance
enrichment, immutable history, dangling-reference rejection, tamper rejection, and
holding-over-watchlist overlap resolution. Empty
portfolio and watchlist readiness is successful.

## Screening acceptance

Tests cover explicit update, offline run, bounded refresh, configuration limits, partial price
failure, rate limits, fetch truncation, missing bars, held-instrument exclusion, deterministic
candidate order, and Alpha Vantage plan/outputsize/lookback validation before acquisition.
Network-client contract tests inject transports and require no live account.

## Analysis workspace acceptance

Tests build context from immutable portfolio, watchlist, decision, and screening inputs. They verify
stable context ID and bytes, exact previous deltas, evidence identifiers, missing-input diagnostics,
holding and candidate separation, and matching Markdown.

Privacy tests reject quantities, acquisition prices, account types, CSV paths, personal identifiers,
credentials, external research, and conversations in `context.json`. Existing reports and local
legacy artifacts are neither modified nor automatically deleted.

## Required gate

```shell
make format-check
make lint
make typecheck
make test
make check
```

Before publication, maintainers also run `make evidence`, review the final diff against
`origin/develop`, and attest the frozen commit. Distribution checks build every catalog package and
install each wheel independently on supported Python versions.

CLI, Makefile, VS Code Tasks, Run and Debug configurations, capabilities metadata, schemas, and user
documentation form one tested operational contract. VS Code JSON remains ASCII English so the
shared entry point is stable across editor locales.
