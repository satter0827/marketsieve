# Quality

Quality evidence is part of each behavior change. Planned checks do not count as evidence until the
corresponding implementation and tests exist.

## Domain acceptance

The Offline Analysis Preview must test:

- ambiguous instruments, invalid market identifiers, and naive timestamps;
- OHLC and volume invariants, date ordering, duplicates, and requested ranges;
- raw versus adjusted semantics, completeness, and provenance;
- deterministic Japanese and U.S. synthetic fixtures;
- SMA20 arithmetic, exact 20-observation boundaries, equality, and state transitions;
- explicit insufficient history and the absence of future-information leakage;
- stable evidence and results for identical inputs;
- the source contract against its first synthetic implementation.

Tests cover unit behavior, application integration, CLI execution, and structural boundaries. No
test depends on network access, provider credentials, local portfolio data, or wall-clock timing.

## Repository acceptance

The SDK must not import the application, configuration, logging, network, database, delivery, or
LLM infrastructure. Public artifacts must contain only allowlisted SDK files and required package
metadata. Temporary notes, tests, caches, local configuration, the application, and generated
reports remain excluded.

Documentation structure tests verify the formal-design index, local links, required design files,
temporary-note naming, and the absence of duplicate legacy authorities.

## Required gate

Every handoff runs the focused checks used during development and then:

```shell
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
uv run python scripts/quality_gate.py check all
```

A failure is corrected and the affected checks are rerun. Environment or tool failures are reported
as such and are not presented as successful test evidence.
