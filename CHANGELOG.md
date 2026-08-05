# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and stable releases
will follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
