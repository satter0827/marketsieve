# Quality

## Market Snapshot acceptance

Synthetic tests cover observation windows, zero denominators, date alignment, missing benchmarks,
overlapping memberships, and deterministic identity. Every defined field exists in exactly one of a
security's value or missing maps.

Adapter tests mock multi-symbol prices, company information, statements, empty responses, rate
limits, retries, and partial failures. Explicit live smoke tests cover Japanese and U.S. securities
plus fixed benchmarks only when enabled.

Integration tests verify one row per constituent, JSONL/CSV agreement, missing-code preservation,
self-contained HTML, separated definitions and quality, neutral summaries, resume enforcement,
history and offline filters, TOPIX proxy identity, split consistency, schemas, removed command
absence, and no Excel output.

## Security Research acceptance

Contract tests cover request bounds, normalized company values, annual and quarterly facts, price
history, events, partial failures, and response identity. Repository tests verify complete artifact
inventory, canonical JSON/JSONL, Snapshot context, deterministic identity, projection tamper
detection, offline history, exact latest selection, schemas, and no Excel output.

## Data quality

Readiness does not discard rows. Overall and per-index coverage come from explicit price success.
Field-group coverage and reason counts expose limitations. Retrieval-time facts are not presented as
historical knowledge. External interpretation never becomes evidence state, and missing values or
outliers are never silently corrected.

## Repository acceptance

The complete gate runs formatting, lint, strict type checks, import-boundary validation, structure
tests, at least 90% line coverage, schemas, reproducible offline smoke checks, secret scanning,
package builds, isolated installation, and external plugin compatibility checks.
