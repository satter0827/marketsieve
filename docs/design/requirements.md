# Requirements

## Product objective

MarketSieve gives a human or external analysis agent a broad, reproducible view of Japanese and U.S.
equities before any security-specific research. The primary evidence is a complete rectangular
matrix, not a candidate list. The product informs research; it does not choose securities or place
orders.

## Market matrix

- **MAT-01:** One run covers the built-in Nikkei 225, TOPIX 500, S&P 500, Dow 30, and Nasdaq-100
  constituent assets selected by configuration.
- **MAT-02:** Securities are deduplicated by exchange-qualified identity and retain every index
  membership. Every constituent appears once whether acquisition succeeds or fails.
- **MAT-03:** yfinance is the only runtime matrix source and requires no account, key, registration,
  or source fallback.
- **MAT-04:** Every row has the same field set. Each field has either a provider-derived or
  deterministically calculated value, or one stable missing-reason code.
- **MAT-05:** Calculations cover identity, classification, price, size, return, trend, momentum,
  risk, liquidity, index-relative behavior, financial statements, growth, profitability, safety,
  and valuation.
- **MAT-06:** The system never imputes, zero-fills, clips, replaces outliers, scores, ranks, or emits
  a trading recommendation.
- **MAT-07:** `securities.jsonl` is authoritative. CSV, self-contained HTML, summaries, and Markdown
  are deterministic projections and no Excel-format artifact is created.
- **MAT-08:** Matrix identity commits to the constituent assets, configuration, field definitions,
  source version, input snapshot, rows, summaries, and failures.
- **MAT-09:** Interrupted request state is separate from immutable objects. Resume accepts only the
  identical request fingerprint.
- **MAT-10:** A ready matrix meets 95% overall and 90% per-index price coverage by default. Failure
  to meet a threshold remains visible and never triggers another provider.

## Stored views and AI context

- **VIEW-01:** `matrix show`, `matrix row`, and `matrix compare` verify and read stored matrix data
  without network access or indicator recalculation.
- **VIEW-02:** `analysis-context/v2` identifies one matrix and references its definitions, summary,
  authoritative JSONL, failures, and coverage without copying security rows.
- **VIEW-03:** Matrix analysis describes aggregate breadth, distributions, risk, liquidity,
  valuation, profitability, growth, concentration, sectors, and missingness. It does not identify a
  preferred security.

## Maintained non-matrix capabilities

- **FND-01:** The public SDK owns pure domain and calculation rules and has no CLI, configuration,
  storage, network, delivery, database, or model-provider dependency.
- **FND-02:** Extension contracts and installed adapters preserve exact request and provenance
  boundaries. Generic source and snapshot capabilities remain available for non-matrix workflows.
- **OPS-01:** Portfolio import, watchlists, daily and weekly reports, and deterministic experiments
  remain supported and independent from broad matrix generation.
- **OPS-02:** Generated state remains below `.marketsieve`; private holdings and live generated
  reports are never committed.

## Exclusions

MarketSieve does not execute an LLM, browse news, send messages, schedule unattended work, manage
credentials, place orders, or automatically adopt an analysis conclusion. Existing legacy local
files are not deleted, migrated, or read through removed schemas.
