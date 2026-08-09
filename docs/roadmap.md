# Roadmap to 1.0.0

MarketSieve 1.0 freezes a dependable evidence-workbench contract. It does not add another product
domain. The release is ready when a new local user can repeatedly build, inspect, verify, and hand
off Market Snapshots and Security Research Packs without hidden state or undocumented recovery.

## 1.0.0rc1

The release candidate freezes these surfaces:

- The five top-level CLI entries and their machine-readable capabilities.
- The three public SDK modules, extension contracts, and four public distributions.
- Snapshot v9, Research v9, Explorer v5, capabilities v11, and every record schema packaged with the
  CLI.
- `marketsieve.settings.toml` as optional execution and quality settings; all analytical scope
  remains an explicit invocation input.
- GitHub Releases as the only project distribution channel.
- Ubuntu and macOS on Python 3.12, 3.13, and 3.14.

Before the candidate is tagged:

1. A fresh checkout completes setup, doctor, JP capture, US capture, saved-data query, Snapshot
   preview, one exact-instrument Research build, Research preview, and artifact diagnosis using the
   documented commands.
2. Three consecutive JP and US close cycles publish valid objects without manual repair. Each cycle
   verifies manifests, definitions, row counts, quality summaries, quality details, outliers,
   failures, timestamps, units, and Explorer projections.
3. Interrupted acquisition is resumed from its exact request, and an incompatible pre-1.0 object is
   isolated with rebuild guidance without being read, migrated, or deleted.
4. Wheels and source distributions install on every supported OS and Python combination. The CLI
   wheel contains all registered schemas and both Explorer renderer resources.
5. Formatter, lint, type checking, tests, package checks, the complete development gate, and the
   release gate pass for the candidate commit.

`1.0.0rc1` remained an unpublished repository milestone. It has no tag or GitHub Release.

## 1.0.0rc2

The second candidate corrects the frozen extension and operation contracts before first public
publication. Acquisition exposes typed progress without changing evidence identity. Operation v2
persists progress, retry, heartbeat, publication, failure, and cancellation state; TTY stderr shows
the same bounded status while stdout remains one final JSON document. Ctrl+C records exit code 130,
preserves published Research Packs, and provides the exact Market resume command.

The repeated JP and US operational checks and the complete release gate restart from the final rc2
develop commit. `v1.0.0rc2` is published as a GitHub prerelease only after the verified main build is
matched to its annotated tag. PyPI remains outside the publication path.

## 1.0.0

Only release-blocking corrections are accepted after `1.0.0rc1`. A correction that changes a frozen
machine contract creates another release candidate and restarts the repeated-operation checks.

The stable release uses the same verified build-once artifacts as its successful main-branch gate.
It is promoted when:

- No unresolved defect can corrupt, misidentify, or silently omit saved evidence.
- No supported command requires a legacy object, tracked local settings, environment file, portfolio,
  watchlist, spreadsheet, or network access for saved-data inspection.
- English design documents and user-facing README files describe the same current behavior,
  commands, versions, platform support, and recovery model.
- The release notes state the unsupported pre-1.0 boundary and the rebuild path.

## After 1.0.0

- Refresh built-in constituent assets through a reviewed, reproducible process when official index
  membership changes.
- Improve acquisition efficiency without changing failure semantics, content identity, or the
  yfinance-only source boundary.
- Add an MCP transport only after more than one client needs the existing application boundary.
- Invoke one-shot close captures from an external scheduler only after local recovery history is
  sufficient.

Portfolio state, watchlists, scores, recommendations, model execution, notifications, scheduling,
daemons, and additional market-data providers remain outside this roadmap.
