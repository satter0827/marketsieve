# Quality

Quality evidence is part of each behavior change. Planned checks do not count as evidence until the
corresponding implementation and tests exist.

## Domain acceptance

The Offline Analysis Preview tests:

- ambiguous instruments, invalid market identifiers, and naive timestamps;
- OHLC and volume invariants, date ordering, duplicates, and requested ranges;
- raw versus adjusted semantics, completeness, and provenance;
- deterministic Japanese and U.S. synthetic fixtures;
- SMA20 arithmetic, exact 20-observation boundaries, equality, and state transitions;
- explicit insufficient history and the absence of future-information leakage;
- stable evidence and results for identical inputs;
- the source contract against its first synthetic implementation.

The historical-report candidate additionally tests:

- independent source retrieval at every replay instant and rejection of invalid schedules;
- stable replay, report, and evidence identities for identical inputs;
- latest-state and transition-only report projection, including insufficient history;
- Rich, text, and schema-valid JSON projections across TTY and non-TTY output;
- capability metadata against the actual command and option definitions;
- user output, errors, and opt-in structured logs on their defined streams.

Tests cover unit behavior, application integration, CLI execution, and structural boundaries. No
test depends on network access, provider credentials, local portfolio data, or wall-clock timing.

## Repository acceptance

The SDK must not import the application, configuration, logging, network, database, delivery, or
LLM infrastructure. Public artifacts must contain only allowlisted SDK files and required package
metadata. Temporary notes, tests, caches, local configuration, the application, and generated
reports remain excluded.

Documentation structure tests verify the formal-design index, local links, required design files,
temporary-note naming, and the absence of duplicate legacy authorities.

## Evidence gates

The Develop Gate runs formatting, lint, strict typing, import contracts, structure and behavior
tests, branch coverage, schema validation, CLI smoke tests, package checks, public-artifact
inspection, isolated installation, and whitespace validation once. Its machine-readable evidence
is retained under `.marketsieve/artifacts/checks/<commit>/`.

The Review Gate reuses that evidence. It creates `review.json` as the authoritative report,
`summary.md` as its deterministic human projection, a text-only patch, supporting evidence, JSON
Lines logs, and checksums under `.marketsieve/artifacts/review/<commit>/`. Schema, commit identity,
references, summary projection, and checksums must validate before merge.

The Release Gate builds the SDK distribution once and verifies the same artifact on every supported
Python version. It admits only a same-repository `develop -> main` pull request. Tags, GitHub
Releases, and package publication remain separate human-authorized operations.

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
make review
```

A failure is corrected and the affected checks are rerun. Environment or tool failures are reported
as such and are not presented as successful test evidence.
