# Quality

Quality evidence is part of each behavior change. Planned checks do not count as evidence until the
corresponding implementation and tests exist.

## Domain acceptance

The Offline Analysis Preview tests:

- ambiguous instruments, invalid market identifiers, and naive timestamps;
- OHLC and volume invariants, date ordering, duplicates, and requested ranges;
- raw versus adjusted semantics, completeness, and provenance;
- deterministic Japanese and U.S. synthetic fixtures;
- all seven indicator definitions independent of ambient decimal precision with exact warm-up
  boundaries;
- explicit insufficient history and the absence of future-information leakage across UTC offsets
  and daylight-saving folds;
- stable evidence and results for identical inputs;
- stable decision-report JSON and Markdown for identical inputs;
- canonical report reconstruction, tamper detection, and all-indeterminate latest protection;
- FRED pagination, missing observations, revision bounds, rate limits, and injected transport;
- the source contracts against synthetic transports;
- stable snapshot, section, comparison, report, and evidence identities for identical inputs;
- Japanese and English Rich, text, and schema-valid JSON projections;
- capability metadata against the actual command and option definitions;
- user output, errors, and opt-in structured logs on their defined streams.

Tests cover unit behavior, application integration, CLI execution, and structural boundaries. No
test depends on network access, provider credentials, local portfolio data, or wall-clock timing.

The CSV snapshot vertical slice additionally tests strict manifest metadata, publication and
retrieval availability, path containment, deterministic object identity, idempotent import,
normalized-content tamper detection, interrupted-write exclusion, explicit plugin metadata, and
the offline import-to-inspect CLI path.

Indicator acceptance uses fixed reference vectors for all seven definitions, exact warm-up
boundaries, invalid parameter checks, stable evidence, canonical decimals, and an ambient Decimal
context changed to two digits. CLI tests validate schema-conforming analysis from a stored CSV
snapshot and explicit technical-section incompleteness.

## Repository acceptance

The SDK must not import the application, configuration, logging, network, database, delivery, or
LLM infrastructure. Public artifacts must contain only allowlisted SDK files and required package
metadata. Temporary notes, tests, caches, local configuration, the application, and generated
reports remain excluded.

Documentation structure tests verify the formal-design index, local links, required design files,
temporary-note naming, and the absence of duplicate legacy authorities.

Repository tests also verify rename-normalized evidence paths, VS Code bytecode-cache placement,
Ruleset drift detection, and timezone availability when the operating system has no timezone
database.

## Evidence gates

The Develop Gate runs formatting, lint, strict typing, import contracts, structure and behavior
tests, branch coverage, schema validation, CLI smoke tests, package checks, public-artifact
inspection, isolated installation, and whitespace validation once. Its machine-readable evidence
is retained under `.marketsieve/artifacts/checks/<commit>/`.

The Evidence Gate reuses that evidence. It creates `review.json` as the authoritative report,
`summary.md` as its deterministic human projection, a text-only patch, supporting evidence, JSON
Lines logs, and checksums under `.marketsieve/artifacts/review/<commit>/`. Schema, commit identity,
references, summary projection, and checksums must validate before merge. This bundle is review
input; it does not claim that semantic code review occurred.

After semantic review succeeds, `make review-attest REVIEWED_SHA=<full-commit-sha>` validates the
matching local evidence and clean HEAD before publishing the `Pre-PR Review` commit status. The
develop ruleset requires that status for the current head; a later commit cannot inherit it.

The Release Gate builds every distribution in the root public-package catalog and the locked
multi-Python runtime
wheelhouse once, then verifies and installs the same checksummed artifact set on every supported
Python version. Compatibility jobs do not compare against runner-local regenerated dependencies.
It admits only a same-repository
`develop -> main` pull request. Tags, GitHub Releases, and package publication remain separate
human-authorized operations.

Repository-owned machine contracts use JSON Schema Draft 2020-12. Each schema has a stable
identifier and a SemVer payload version: breaking changes increment major, compatible field
additions increment minor, and clarifications that preserve constraints increment patch. Consumers
reject unknown major versions. Established formats such as JUnit XML and coverage JSON remain in
their native form rather than being wrapped in repository-specific schemas.

## Required gate

Every handoff runs the focused checks used during development and then:

```shell
make format-check
make lint
make typecheck
make test
make check
make evidence
```

A failure is corrected and the affected checks are rerun. Environment or tool failures are reported
as such and are not presented as successful test evidence.

## Approved 0.2 and 0.3 acceptance additions

The target gate adds deterministic reference vectors for every indicator, ambient-decimal-context
tests, snapshot identity and atomicity tests, publication-versus-retrieval availability tests, and
contract suites shared by CSV, J-Quants, Alpha Vantage, and FRED. Network clients are injected.
Default tests use synthetic responses and never require accounts, credentials, wall-clock timing,
or network access. Live provider checks use an explicit marker and manual credentials.

CLI acceptance covers Japanese and English Rich and text projections, versioned JSON, partial
sections, incompatible comparison warnings, installed plugin metadata without plugin import, and
execution of only the selected source profile. Package acceptance builds and installs the SDK,
extension API, CLI, and each source independently before verifying their wheelhouse combinations on
Python 3.12 through 3.14.

Agent acceptance uses test-local models for ordinary tests and mocked transports for each real provider.
It covers invalid schemas, unknown facts, numeric additions, recommendation language, timeouts,
cloud consent, loopback restrictions, and deterministic fallback. Fake tests prove orchestration
and safety behavior, not provider model behavior.

CLI acceptance additionally verifies that provider selection is mandatory, cloud dry-run is
credential-free, local doctor is configuration-only, and cloud execution is refused without consent.

Secret acceptance scans tracked files, the reviewed diff, generated evidence, distributions, and
release assets without printing matched values. CI also scans repository history. Tests ensure
credentials are removed from URLs, headers, exceptions, logs, subprocess environments, and stored
request metadata.

## 0.4.0 acceptance target

Personal Close Brief acceptance adds:

- complete reference cases for every held and unheld decision branch;
- stable policy and decision identities for identical inputs;
- explicit confidence reduction and indeterminate results for missing evidence;
- partial-instrument success and all-instrument failure behavior in daily orchestration;
- Japanese, U.S., daylight-saving, non-trading-day, stale-data, and future-data cases;
- portfolio normalization without retained source files or personal identifiers;
- conclusion-first Japanese and English Rich, text, quiet, JSON, and Markdown projections;
- proof that model success or failure cannot alter a static report;
- wheel-installed external adapter discovery and public conformance tests.

Test doubles prove bounded agent behavior without entering production provider selection.
