# Requirements

## Product objective

MarketSieve helps a full-time worker review a small Japanese and U.S. equity portfolio without
turning analysis into a second full-time job. It converts explicit data and policy inputs into
reproducible static decisions, candidate screens, and history-comparable analysis context.

MarketSieve does not run a language model, send messages, place orders, automate a brokerage
session, or persist external research and conversations.

## Implemented foundation

- **FND-01:** `marketsieve` is a typed, I/O-independent public SDK.
- **FND-02:** Market identity, time, observations, indicators, provenance, decisions, and evidence
  use deterministic public semantics.
- **FND-03:** CSV, J-Quants, Alpha Vantage, FRED, SEC, and EDINET are explicit sources with no
  implicit fallback, retry, provider merging, or request shortening.
- **FND-04:** Verified immutable snapshots support offline inspection, comparison, screening,
  reporting, and Strategy Lab runs.
- **FND-05:** Repository gates verify dependency direction, schemas, distributions, isolated
  installation, static types, formatting, lint, and tests.
- **FND-06:** Static analysis context exposes only verified local artifacts and privacy-bounded
  projections for external tools.

## Portfolio and watchlist

- **PFW-01:** Broker import owns holdings only. `portfolio-result/v3` contains no watchlist item.
- **PFW-02:** A verified empty twelve-column Rakuten `assetbalance(all)` export becomes a valid
  empty holdings observation without retaining its path, bytes, customer identity, or account
  identity.
- **PFW-03:** Unsupported non-empty Rakuten details, contradictory security balances, unknown
  sections, malformed rows, and invalid encoding fail explicitly.
- **PFW-04:** Watchlist revisions are independent content-addressed objects with exact previous
  revision and optional screening provenance.
- **PFW-05:** Daily analysis composes the latest holdings and watchlist in memory. A holding wins
  when the same instrument appears in both sources.
- **PFW-06:** Empty holdings and an empty watchlist are ready states. Readiness points to bounded
  discovery or explicit watchlist entry.

## Decisions and screening

- **DEC-01:** The balanced medium-term Decision Policy is deterministic and produces an explicit
  held or unheld action, confidence, evidence, invalidation conditions, and next action.
- **DEC-02:** Daily and weekly commands create immutable `decision-report/v1` JSON and deterministic
  Markdown without model execution.
- **DEC-03:** `screen update` and `screen run` retain explicit acquisition and offline-evaluation
  boundaries.
- **DEC-04:** `screen refresh` performs bounded universe acquisition, bounded daily-bar acquisition,
  and offline screening in that order.
- **DEC-05:** Fetch, lookback, processing, and display limits are configuration values. Partial
  failure, rate limit, truncation, and missing data remain diagnostics.
- **DEC-06:** Candidate actions identify additional-research states and never authorize a purchase.
  Promotion to the watchlist requires an explicit human command.

## Static analysis workspace

- **ANL-01:** `analysis build` writes `README.md`, canonical `analysis-context/v1` JSON, and
  deterministic `analysis.md` below `.marketsieve/analysis`.
- **ANL-02:** Context contains artifact IDs, as-of times, holdings identities, watchlist history,
  latest decision and screening reports, exact previous deltas, evidence, missing inputs, and
  diagnostics.
- **ANL-03:** Context excludes quantities, acquisition prices, account types, local CSV paths,
  personal identifiers, and credentials.
- **ANL-04:** Identical verified inputs produce the same context ID and identical bytes.
- **ANL-05:** News, external claims, conversations, and external-tool output are not MarketSieve
  artifacts.

## Product constraints

- Symbols are always exchange-qualified by MIC.
- Read-only operations never acquire data implicitly.
- Missing, stale, incompatible, and unavailable evidence remains visible.
- Provider credentials enter through provider-specific environment variables only.
- The SDK remains independent from CLI, configuration, logging, network, persistence, broker, and
  external-tool infrastructure.
- Current exclusions include orders, brokerage automation, background services, messaging,
  browser automation, opaque scores, arbitrary expression evaluation, and redistribution of live
  provider or personal data.
