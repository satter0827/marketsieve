# Design

This directory is the normative system-level design for behavior implemented on `develop`.
Planned outcomes remain in the roadmap until their code, schemas, tests, and audience documentation
ship together.

## Documents

- [Requirements](requirements.md) defines product outcomes, constraints, and exclusions.
- [Domain](domain.md) defines market and analysis semantics.
- [Architecture](architecture.md) defines component ownership and dependency boundaries.
- [Interfaces](interfaces.md) defines current commands and approved interaction boundaries.
- [Quality](quality.md) defines acceptance evidence and invariants.
- [Operations](operations.md) defines supported local operation.
- [Lifecycle](lifecycle.md) separates automated work, human decisions, and manual procedures.

Each concern has one authoritative document. Cross-references should link to that document instead
of copying its rules. When an approved target becomes implemented, the same change must move its
description into current behavior and update tests and audience guides.
