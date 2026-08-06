# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and stable releases
will follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
