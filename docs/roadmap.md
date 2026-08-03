# Roadmap

The roadmap is ordered by dependency and evidence. A later milestone does not begin by assuming an
earlier contract that has not been implemented and tested.

## Foundation

- Build and install the typed `marketsieve` SDK.
- Run the repository-local CLI without network access or secrets.
- Enforce dependency and distribution boundaries in local and CI gates.
- Establish the `develop -> main` release-review path.

## Market semantics

- Define exchange-aware instruments, currencies, sessions, and timezone-aware observations.
- Reject ambiguous symbols and naive timestamps at public boundaries.
- Document adjustment and as-of semantics before accepting historical data.

## Offline analysis

- Add licensed-for-repository synthetic daily fixtures for Japanese and U.S. equities.
- Implement the first deterministic indicator and state-change signal.
- Add historical replay that prevents future-information leakage.
- Generate channel-neutral template reports with evidence references.
- Deliver reports through a console adapter.

The completed offline analysis milestone is the first `0.1.0` release candidate.

## Personal operation

- Add selected live-data adapters after reviewing terms and redistribution constraints.
- Persist operational state and delivery receipts independently from structured logs.
- Add SMTP email delivery, followed by LINE Messaging API delivery.
- Add schedules as external interfaces into the same application pipeline.

## Assisted reporting

- Publish a report-agent port with the first template and LLM implementations.
- Give report agents validated facts rather than raw authority over calculations or alert decisions.
- Store model, prompt, input, output, and evidence provenance without exposing secrets or recipients.
