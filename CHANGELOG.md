# Changelog

All notable changes are documented here. The project follows Keep a Changelog and uses Semantic
Versioning for stable releases.

## [Unreleased]

## [1.0.0rc3] - 2026-08-10

### Changed

- Advanced capabilities to v13. Each command now declares either a schema-backed document result
  or a loopback server result, and reports external-network and loopback-server effects separately.
- Pinned all four MarketSieve distributions to the same exact version. `doctor` and the release gate
  reject missing distributions and every RC, stable, or patch-level mixture.
- Centralized built-in index runtime identity and query-profile periods in CLI-owned typed
  definitions shared by Market, Research, validation, and stored-data filtering.
- Added an explicit-input release qualification report and a metadata-only stable-promotion guard.
  Release notes are now generated deterministically from this section.

### Fixed

- Removed the nonexistent Preview document schema from the public capability contract.
- Excluded operation v1 records from v2 lists and rejected them from `show` with an explicit,
  functional prune command. Pre-1.0 objects remain unsupported and require reconstruction.
- Changed isolated release verification to install `marketsieve-cli==1.0.0rc3` through the same
  `--find-links` dependency-resolution path documented for users.

## [1.0.0rc2] - 2026-08-09

### Changed

- Added typed, evidence-neutral acquisition progress for equity batches, market indicators, and
  Security Research domains, with bounded updates, retry observations, and TTY-only stderr lines.
- Advanced operation runs and events to v2 with current progress, updated time, heartbeat events,
  published object IDs, cancelled status, and exit code 130.
- Advanced capabilities to v12 while retaining Snapshot v9, Research v9, and Explorer v5.

### Fixed

- Cancelled unstarted parallel acquisition work, retained Research Packs published before Ctrl+C,
  and recorded the exact 16-character Market resume ID and command.
- Restricted the secret path gate to credential data, dedicated secret directories, and private-key
  file types so the scanner no longer rejects its own Python implementation.

`1.0.0rc1` was not tagged or published. `1.0.0rc2` is the first public 1.0 release candidate.

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
