# Documentation

MarketSieve separates normative design, planned work, temporary investigation, and audience guides
so that readers can tell what the system guarantees today and what remains proposed.

## Sources of authority

The following sources have distinct authority. A disagreement between them is a defect and must be
resolved in the same change that alters the behavior.

1. Tested code, public types, and command behavior define the exact executable contract.
2. [Design](design/README.md) defines system-level requirements, semantics, boundaries, and quality
   policy for implemented behavior and approved near-term work.
3. [Roadmap](roadmap.md) orders planned outcomes. It is not a description of current behavior.
4. [Notes](notes/README.md) contain temporary, non-normative investigation and discussion.
5. The root README files summarize the project for users and contributors.

## Audiences

- SDK users should start with the root README and the design interfaces.
- Adapter authors should read the domain, architecture, interfaces, and quality design.
- Maintainers and coding agents should also read operations and lifecycle design.

## Change policy

Formal design is written in English. It describes implemented behavior in the present tense and
approved next-milestone behavior under an explicit target heading. Speculative work belongs in the
roadmap or a dated note. Exact public Python signatures are documented only when a working
implementation and tests establish them.

Architecture decision records are not used yet. If persistent decision history becomes necessary,
it will be introduced as a separate record set and will not replace the current-state design.
