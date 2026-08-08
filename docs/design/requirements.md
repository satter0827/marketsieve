# Requirements

## Product objective

MarketSieve gives a human or external agent a broad, reproducible view of Japanese and U.S. equities
before focused research. The primary evidence is a complete market cross-section, not a candidate
list. The product informs research; it does not choose securities or place orders.

## Market Snapshot

- **MKT-01:** One run covers configured built-in Nikkei 225, TOPIX 500, S&P 500, Dow 30, and
  Nasdaq-100 constituents.
- **MKT-02:** Securities are deduplicated by exchange-qualified identity, retain every membership,
  and appear once whether acquisition succeeds or fails.
- **MKT-03:** yfinance is the only runtime source and requires no account, key, registration, or
  provider fallback.
- **MKT-04:** Every security has the same field set. Each field has one value or stable missing code.
- **MKT-05:** Calculations cover identity, classification, price, size, return, trend, momentum,
  risk, liquidity, relative behavior, financials, growth, profitability, safety, and valuation.
- **MKT-06:** The system never imputes, zero-fills, clips, replaces outliers, scores, ranks, or emits
  a trading recommendation.
- **MKT-07:** `securities.jsonl` is authoritative. CSV, self-contained HTML, JSON summaries, and
  Markdown are projections. No Excel artifact is created.
- **MKT-08:** Snapshot identity commits to assets, configuration, definitions, source evidence,
  rows, aggregates, quality, failures, and artifact inventory.
- **MKT-09:** Interrupted state is separate. Resume accepts only the identical fingerprint and date.
- **MKT-10:** Default readiness requires 95% overall and 90% per-index price coverage. Failure is
  visible and never triggers another provider.

## Security Research Pack

- **RES-01:** Focused research accepts only a security present in a selected verified Snapshot.
- **RES-02:** It acquires adjusted daily price history, retrieval-time company facts, annual and
  quarterly financial facts, dividends, splits, earnings events, and exact failures from yfinance.
- **RES-03:** The pack preserves the selected Snapshot plus matching market, index, sector, and
  industry context without copying the full Snapshot.
- **RES-04:** JSON and JSONL evidence is authoritative. README, Markdown, and self-contained HTML are
  verified projections. The directory has no external file reference.
- **RES-05:** Missing publication timestamps are not guessed. Affected facts are explicitly marked
  as known at retrieval rather than historical point-in-time evidence.
- **RES-06:** The pack contains no prompt, prescribed analysis sequence, model output, score,
  ranking, recommendation, or order instruction.
- **RES-07:** Transport is outside the use case. A future MCP adapter reuses the same typed service
  and schemas and cannot own provider calls or persistence.

## Stored views and portable context

- **VIEW-01:** `market list`, `show`, `query`, `security`, and `compare`, plus `research list` and
  `show`, verify saved data without network access or recalculation.
- **VIEW-02:** Each object is self-contained and transferable. README explains data and file roles
  without embedding an agent prompt, reasoning sequence, question, or conclusion format.
- **VIEW-03:** External interpretation is never written into immutable evidence objects.

## Maintained capabilities

- **FND-01:** The SDK has no CLI, configuration, storage, network, delivery, database, or model
  dependency.
- **FND-02:** Extension contracts preserve exact requests and provenance. Generic source and
  snapshot capabilities remain independent.
- **OPS-01:** Portfolio, watchlist, daily, weekly, and experiment workflows remain supported and
  separate from broad-market and focused-research generation.
- **OPS-02:** Generated state stays below `.marketsieve`; private holdings and live data are not
  committed.

## Exclusions

MarketSieve does not execute an LLM, browse news, send messages, schedule unattended work, manage
credentials, place orders, or adopt an investment conclusion. Pre-0.11 market objects are not
migrated or read by current commands.
