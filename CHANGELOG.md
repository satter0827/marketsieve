# Changelog

All notable changes are documented here. The project follows Keep a Changelog and uses Semantic
Versioning for stable releases.

## [Unreleased]

## [1.0.0rc1] - 2026-08-09

### Changed

- Defined MarketSieve as a local evidence workbench with five top-level commands: `market`,
  `research`, `operations`, `doctor`, and `capabilities`.
- Reduced the public SDK to `marketsieve.model`, `marketsieve.indicators`, and
  `marketsieve.fields`; moved deterministic provider fixtures to
  `marketsieve_extension_api.testing`.
- Renamed internal matrix concepts to Snapshot concepts and split field definitions, calculations,
  saved-data querying, aggregate projections, storage, and Explorer rendering by responsibility.
- Packaged all machine schemas with the CLI and validate immutable Snapshot and Research documents
  before publication and whenever an object is read.
- Advanced Snapshot and Research contracts to v9, Explorer data and renderer contracts to v5, and
  capabilities to v11. Earlier local objects are reported as incompatible and are never migrated or
  deleted automatically.
- Moved Explorer HTML into packaged renderer resources while preserving object-local, no-CDN
  operation through the restricted preview server.
- Published repository distributions only through verified GitHub Releases. Third-party runtime
  dependencies are resolved by pip from the configured package index.
- Added release verification on Ubuntu and macOS with Python 3.12, 3.13, and 3.14, including
  `1.0.0rcN` release versions.

### Fixed

- Bound normalized yfinance price bars to the exact requested date window and classify provider
  data that predates the request as stale instead of rejecting the complete batch.
- Connected interrupted Snapshot acquisition to operation history and CLI recovery through one
  exact resume run ID and command.

### Removed

- Removed legacy `preview`, `artifacts`, and `run` top-level commands, the tracked settings file,
  `.env.example`, obsolete schema generations, compatibility loaders, and unused SDK request and
  series abstractions.
- Removed PyPI publication and release staging. GitHub Releases are the only project distribution
  channel.

## Pre-1.0 development history

### 0.12.0 through 0.19.4

The product boundary was rebuilt around broad Market Snapshots and focused Security Research Packs.
These releases introduced explicit invocation inputs, yfinance-only acquisition, immutable
content-addressed objects, JSON and JSONL authorities, quality and failure evidence, local Explorer
views, stored-data queries and comparisons, operation history, and a narrow typed SDK. Portfolio,
watchlist, recommendation, experiment, generic-provider, CSV, and spreadsheet workflows were
removed from the product.

### 0.1.0 through 0.11.0

The initial releases established typed market models, deterministic indicators, CLI output
contracts, package boundaries, extension discovery, evidence provenance, review gates, release
gates, and the first broad-market artifact prototypes. Their public contracts were experimental and
are not supported by the 1.0 line.
