# Requirements

## Product objective

MarketSieve helps a full-time worker operate a small personal portfolio of Japanese and U.S.
equities without turning routine analysis into another full-time job. It converts explicit market,
portfolio, and policy inputs into reproducible close-of-market and weekly decisions.

The product optimizes for short, evidence-backed review sessions. It may conclude that no action is
needed. It does not place orders, automate a brokerage session, run continuously, or deliver
notifications.

## Implemented foundation

- **FND-01:** `marketsieve` is a typed, I/O-independent public SDK.
- **FND-02:** Market identity, time, daily bars, financial facts, events, economic series,
  indicators, provenance, and evidence use deterministic public semantics.
- **FND-03:** CSV, J-Quants, Alpha Vantage, FRED, SEC, and EDINET are explicit acquisition paths
  with no implicit fallback or provider merging.
- **FND-04:** Verified immutable snapshots support offline inspection, analysis, comparison, and
  reporting.
- **FND-05:** The optional agent can explain only an immutable decision-report fact catalog through
  an explicitly selected local or cloud model. Explanation artifacts cannot modify report objects.
- **FND-06:** Local and CI gates verify tests, dependency direction, distributions, and isolated
  installation on supported Python versions.
- **FND-07:** FRED supplies explicit economic-series observations with observation, retrieval, and
  revision time semantics.
- **FND-08:** Financial acquisitions preserve filing identity, amendment linkage, public time, and
  fact-to-filing provenance so historical analysis can exclude facts not yet available.
- **FND-09:** Financial trends select only compatible annual observations known at the requested
  instant and retain deterministic period, metric, and evidence identities.

## 0.4.0 Personal Close Brief target

- **PCB-01:** A portfolio snapshot represents holdings and watch items without brokerage-specific
  types in the SDK.
- **PCB-02:** A versioned decision policy produces an explicit held or unheld decision, confidence,
  supporting evidence, opposing evidence, invalidation conditions, and next action.
- **PCB-03:** `daily jp`, `daily us`, and `weekly` create immutable static reports from explicit
  inputs and never require an LLM.
- **PCB-04:** The same inputs, policy, configuration, and as-of instant produce the same decision,
  report identity, JSON, and Markdown.
- **PCB-05:** A partial run retains failed instruments as indeterminate. A run with no analyzable
  instrument does not update a latest-report reference.
- **PCB-06:** Human output leads with the conclusion, items needing attention, changes, and the next
  action. No-action days are successful outcomes.
- **PCB-07:** A Rakuten importer normalizes only formats established by anonymized real fixtures and
  stores neither the source CSV nor personal identifiers.
- **PCB-08:** An agent explanation consumes an immutable decision report and cannot alter its
  decisions, values, evidence, or identity.
- **PCB-09:** External adapters can be independently developed and installed against a versioned
  extension API with public conformance tests.

## Product constraints

- Japanese and U.S. instruments remain exchange-qualified. Symbols alone are not identities.
- Acquisition is explicit. Read-only analysis never silently performs network access.
- Missing, stale, incompatible, or unavailable data remains visible and cannot be converted to a
  neutral value.
- Thresholds and periods are named policy settings and are recorded in report evidence.
- Provider credentials, account identifiers, source portfolio files, local state, and generated
  reports are never tracked or distributed.
- SDK code remains independent from the CLI, configuration, logging, network clients, persistence,
  delivery, broker adapters, and LLM providers.
- New public capability contracts require a working implementation and executable conformance
  tests in the same change.

## Exclusions through 0.7.0

- Order placement and brokerage automation
- Browser automation and session handling
- Background scheduling and always-on services
- LINE, email, and other delivery channels
- Implicit provider fallback or provider merging
- Opaque investment scores
- Arbitrary Python expressions or `eval` in screening rules
- Redistribution of provider market data or live personal portfolio data
