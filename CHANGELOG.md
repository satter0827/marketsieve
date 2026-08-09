# Changelog

## [0.19.3] - 2026-08-09

- Validate current-contract objects independently during inventory and classify invalid projections
  as corrupt without failing the full list.
- Keep valid Snapshot and Research history available when an older object uses an obsolete Explorer
  projection.

## [0.19.2] - 2026-08-09

- Correct Snapshot Explorer coverage rendering for structured quality summaries.
- Add readable units, periods, axes, ticks, direct labels, and unit-separated market context panels.
- Improve Research headers and time-series axes while hiding unavailable series from legends.
- Keep Explorer observation counts aligned with the canonical applicable population.

## [0.19.1] - 2026-08-09

- Sorted the internal price-only equity request used by market indicators so full live Snapshot
  generation satisfies the deterministic batch contract after equity acquisition completes.
- Added a regression test for indicator IDs whose contract order differs from their normalized
  internal instrument order.

## [0.19.0] - 2026-08-09

- Added a small stable SDK surface for models, deterministic indicators, and field definitions.
- Added Research line and short-period candlestick views plus unit-separated financial charts and
  structured evidence presentation.
- Refined Snapshot breadth cards, coordinated filters, explicit chart metadata, and quality views.

## [0.18.0] - 2026-08-09

- Isolated current, incompatible, corrupt, and orphan artifacts so legacy Research cannot break
  normal inventory operations.
- Separated market-indicator acquisition from equities with explicit kinds, units, and
  non-applicable equity domains.
- Split quality summary, detail, outlier, and failure evidence; renamed the price-only gate.
- Added locale-independent machine output, unified preview, structured operation runs, query
  funnels, and explicit Snapshot FX conversion.

## [0.17.0] - 2026-08-09

- Replaced the embedded Research Explorer projection with a reference-only v2 contract that reads
  authoritative price, benchmark, financial, event, company, quality, and failure evidence.
- Added selectable 3-month through full-history views for price, moving averages, volume,
  benchmark-relative performance, rolling risk, financial periods, events, and structured evidence.
- Split the former aggregate event state into independent price, company, annual and quarterly
  financial, earnings, dividend, split, and benchmark acquisition states so partial success remains
  usable.

## [0.16.0] - 2026-08-08

- Replaced duplicated embedded Snapshot Explorer data with a reference-only v2 contract that reads
  canonical object files over the restricted local preview server.
- Added coordinated market exploration, paginated securities, URL handoff state, explicit quality
  counts, field-aware unit checks, and bounded local gate parallelism.

## [0.15.1] - 2026-08-08

- Merge overlapping benchmark and market-indicator roles before constructing the all-market
  yfinance batch, preserving unique sorted instrument requests.
- Restrict Explorer security search to identifiers and classification text so numeric observations
  do not create unrelated matches.

## [0.15.0] - 2026-08-08

- Add explicit market-close Capture runs and price-only historical reconstruction with structured
  run state, duplicate detection, future-date checks, and universe-basis safeguards.
- Move operation capabilities and typed requests toward a transport-independent application
  boundary without adding MCP or scheduling dependencies.

## [0.14.0] - 2026-08-08

- Add purpose profiles, neutral ordering and limits, domain projections, and transient budget and
  trading-unit affordability to persisted Snapshot queries.
- Add yfinance market indicators and shared chart-neutral Snapshot and Research Explorer data.
- Add loopback-only preview commands that expose one verified immutable object without directory
  listing or path traversal.

## [0.13.0] - 2026-08-08

- Normalize yfinance percentage-point fields to ratio units at the provider boundary.
- Separate applicability, comparison scope, temporal metadata, normal missing cells, and actual
  acquisition failures in the Snapshot v4 and Research v3 contracts.
- Add field and segment coverage, freshness, unit checks, outlier candidates, and market-sector
  aggregates to quality evidence.
- Measure product packages and scripts with independent statement and branch quality thresholds.
- Consolidate CI evidence in Develop Gate and replace repeated full pre-PR review with semantic
  full-then-delta review.

## [0.12.0] - 2026-08-08

### Added

- Explicit scope, evidence-domain, and history inputs for Market Snapshot and Security Research runs.
- Stored Snapshot diff with definition compatibility checks and multi-security research batches.
- Chart-led, self-contained Snapshot and research Explorers designed for human and AI handoff.

### Changed

- Runtime settings are separated from per-run analytical inputs and use `--settings`.
- Snapshot artifacts use `aggregates.jsonl` and schema v3; research artifacts use schema v2.
- The public workspace contains only core, extension API, CLI, and yfinance source packages.

### Removed

- Portfolio, watchlist, routine reports, generic sources and snapshots, experiments, and their
  providers, schemas, settings, examples, tests, and editor entries.
- CSV output. JSON and JSONL remain authoritative; HTML and Markdown are projections.

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and stable releases
will follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.11.0] - 2026-08-08

### Added

- Broad Market Snapshot commands and schemas for refresh, history, filtering, saved-security reads,
  and comparisons without using matrix terminology as the public product model.
- Snapshot aggregates for all securities, JP and U.S. markets, indices, sectors, and industries,
  with separated field definitions, quality evidence, and self-contained explorer projections.
- On-demand yfinance Security Research Packs for one selected Snapshot security, including up to ten
  years of adjusted prices, company facts, annual and quarterly statements, dividends, splits,
  earnings events, exact failures, and matching market context.
- English daily-use launch configurations and exhaustive Make-backed VS Code tasks for market,
  research, routine, and developer workflows.

### Changed

- Public packages and compatible internal dependencies use version 0.11.0. Capabilities use v4.
- Generated broad-market state now lives below `.marketsieve/market-snapshots`; focused research
  lives below `.marketsieve/research`.
- CLI application protocols are independent from Click and transport details so a future MCP adapter
  can reuse them without introducing another provider or persistence path.

### Removed

- Public `matrix` commands, schemas, configuration name, filenames, and storage contract. The pure
  SDK calculation module remains an internal implementation detail.
- Legacy public schema files and compatibility loading for pre-0.11 market objects.

## [0.10.0] - 2026-08-08

### Added

- Offline matrix history listing and deterministic classification, numeric, presence, and
  missingness queries over saved JSONL rows.
- A self-contained matrix README, missing-reason catalog, and neutral aggregate summary projection.
- Corporate-action consistency validation for adjusted yfinance price histories.

### Changed

- TOPIX 500 relative metrics use the fixed `1308.T` TOPIX-linked ETF proxy because yfinance does
  not return history for `^TOPX`; proxy use is explicit and never selected at runtime.
- Matrix manifests and projections use v2 and public workspace packages use version 0.10.0.
- Readiness checks validate TOML syntax with the standard library before invoking `uv` or installed
  project packages.

### Removed

- The separate analysis workspace, `analysis-context/v2`, its CLI and Make commands, and duplicate
  generated analysis files.
- The destructive `clean-generated` Make target.

## [0.9.0] - 2026-08-07

### Added

- A zero-configuration yfinance source and batch extension contract for adjusted daily prices,
  company profiles, financial statements, and normalized partial failures.
- One deduplicated full-security matrix across the Nikkei 225, TOPIX 500, S&P 500, Dow 30, and
  Nasdaq-100, with a common field catalog and cell-level missing reasons.
- Immutable JSONL authority, typed CSV and self-contained HTML views, aggregate index summaries,
  macro analysis Markdown, and matrix-backed `analysis-context/v2`.
- Offline `matrix show`, `matrix row`, and `matrix compare` views over already calculated rows.
- Per-date exchange-session close validation, including scheduled U.S. shortened sessions.

### Changed

- Public workspace packages now share version 0.9.0 and compatible 0.9 dependency ranges.
- Watchlists, decision reports, analysis context, and capabilities use their v2, v2, v2, and v3
  schemas respectively, without legacy schema loading or automatic migration.
- Broad-market analysis is now matrix-first and records missing provider values without
  substitution, imputation, scoring, ranking, or recommendations.
- BATS identities emitted by the matrix remain valid in watchlists and maintained U.S. providers.

### Removed

- Candidate screening services, stores, policy types, report provenance, CLI commands, and schemas.
- Public single-security inspection, indicator analysis, and legacy equity comparison entry points.
- Excel output; matrix artifacts use JSONL, JSON, CSV, self-contained HTML, and Markdown only.

## [0.8.0] - 2026-08-06

### Added

- Independent content-addressed watchlist revisions with supported MIC metadata and optional
  screening-report provenance.
- Bounded `screen refresh` workflows for Japanese and U.S. candidate discovery.
- A deterministic `analysis-context/v1` workspace with privacy-bounded JSON, matching Markdown,
  exact previous-report deltas, evidence IDs, missing inputs, and diagnostics.
- Ordered VS Code Run and Debug operations for first use, discovery, watchlists, daily analysis,
  weekly reporting, workspace generation, and representative debugging.

### Changed

- Public workspace packages now share version 0.8.0 and compatible 0.8 dependency ranges.
- Portfolio objects use holdings-only `portfolio-result/v3`; watchlists are composed only at daily
  analysis time and holdings take precedence over duplicate watchlist entries.
- Rakuten import accepts the verified anonymous twelve-column empty `assetbalance(all)` form while
  rejecting non-empty, contradictory, malformed, unknown, or incorrectly encoded input.
- Empty holdings and an empty watchlist are valid readiness states that direct users to discovery
  or explicit watchlist entry.

### Removed

- Removed the `marketsieve-agent` and `marketsieve-ai` distributions, all model-provider adapters,
  configuration, credentials, prompts, fallback behavior, and explanation storage.
- Removed manual AI file exchange and the `ai prepare/import/show`, `agent doctor`, `report explain`,
  and `experiment explain` commands and schemas.
- Removed internal model comparison, improvement-review, and messaging plans. Existing local legacy
  artifacts are not deleted but are no longer read.

## [0.7.0] - 2026-08-06

### Added

- An independently installable Rakuten adapter imports the verified CP932 no-holdings
  `assetbalance(all)` form as an empty normalized portfolio without retaining personal source data.
- A versioned portfolio-import extension contract and explicit installed-plugin selection allow
  broker adapters to be developed outside the workspace.
- Strict broker-neutral portfolio CSV import, content-addressed normalized storage, and offline
  `portfolio show` with no source-file retention.
- Knowledge-time-correct annual financial trends and compatible derived metrics in the public SDK,
  with typed period views and deterministic evidence identity.
- Filing identity, amendment linkage, publication-time filtering, and durable fact-to-filing
  provenance for official financial sources.
- An independently installable SEC source for filing histories and standard XBRL company facts.
- An independently installable EDINET source for filing lists and standard XBRL-derived facts.
- Daily Close Brief integration for knowledge-time-correct financial trends, known earnings dates,
  filing amendments, and company-relative valuation ranges.
- Immutable experiment specifications, knowledge-time-correct policy replay, deterministic metrics,
  and run comparison in the public SDK.
- Offline Strategy Lab run, show, and compare commands with content-addressed local artifacts.
- Grounded experiment explanations record prompt, model settings, raw output, validation, and a
  deterministic rendering without changing stored metrics or decisions.
- Typed Japanese and U.S. instrument-universe capabilities with working CSV, J-Quants, and SEC
  implementations, explicit limits, content identity, and visible truncation diagnostics.
- A deterministic balanced candidate screen with eligible actions, transparent evidence counts,
  stable ordering, and no arbitrary expression or opaque score.
- Explicit `screen update`, offline `screen run`, and `screen show` workflows with bounded
  configuration, immutable universe and report objects, atomic latest references, partial-data
  diagnostics, and held-instrument separation.
- Offline weekly reports include fresh stored screening candidates and source report IDs in a
  separate `残った候補` section without changing portfolio decisions or acquiring new data.
- A manual, environment-protected Trusted Publishing workflow reuses the checksum-verified main CI
  artifact for both PyPI and a recoverable GitHub Release.

### Changed

- Portfolio objects now use `portfolio-result/v2`; 0.7.0 intentionally does not read the
  pre-release v1 local format.
- Equity symbols now preserve uppercase dots and hyphens needed by U.S. class-share identifiers.
- Public packages share version 0.7.0 and accept dependencies from the compatible 0.7 minor series
  so adapters can be developed and installed outside this workspace.
- Removed the redundant `equity-report` command and its report-result schema. `inspect` remains the
  canonical sectioned analysis, while durable investment output uses `decision-report/v1`.

## [0.3.0] - 2026-08-05

### Added

- Explanation-only Agent with FakeListLLM as the offline default.
- Explicit LM Studio, OpenAI, Anthropic, and Google model adapters with independent mock transport
  contracts.
- `agent doctor` and `agent explain` commands, credential-free dry runs, and versioned Agent JSON.

### Changed

- Agent output now selects only verified fact identifiers; numbers, dates, evidence, and the
  disclaimer are inserted by a deterministic renderer.
- Every unsafe, ungrounded, invalid, unavailable, or timed-out model response falls back to the
  deterministic template without changing providers.

### Security

- Cloud calls require `--allow-cloud` on the same invocation. Non-loopback LM Studio endpoints
  require `--allow-remote`.
- Models receive no tools, source access, filesystem access, or calculation authority. Credentials
  remain environment-only and are excluded from dry-run output and retained evidence.

## [0.2.0] - 2026-08-05

### Added

- Immutable, content-addressed CSV, J-Quants, and Alpha Vantage snapshots.
- Deterministic SMA, EMA, RSI, MACD, ATR, period-return, and drawdown analysis.
- Sectioned price, technical, financial, valuation, risk, event, and data-quality inspection.
- Offline comparison and report projections with explicit comparability and missing-data reasons.
- Japanese-default human output, English output, and versioned English-keyed JSON contracts.
- Independently installable CLI, extension API, and source distributions.

### Changed

- Replaced the SMA20 replay and report-specific model with one shared sectioned equity view.
- Made acquisition explicit; inspect, analyze, compare, and report never fetch implicitly.

### Security

- Credentials are accepted only from provider-specific environment variables and are redacted from
  requests, snapshots, logs, evidence, and release artifacts.

## [0.1.0] - 2026-08-04

### Added

- Public SDK and repository-local application foundation.
- Time-correct SMA20 historical replay and evidence-backed reports.
- Rich, plain-text, and versioned JSON CLI output with machine-readable capability discovery.
- Exact SMA20 arithmetic, UTC-normalized replay, and transition-only historical reports.
- Commit-bound pre-PR review attestation and reproducible release evidence.

### Changed

- Replaced the offline preview command with the historical `report` command.
- Renamed the evidence-producing Review Gate to Evidence Gate and separated it from semantic review.
