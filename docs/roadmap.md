# Roadmap

The roadmap orders planned outcomes by dependency and evidence. It is not a description of current
behavior; current and approved near-term constraints live in the [formal design](design/README.md).

## Foundation — complete

- Build and install the typed `marketsieve` SDK.
- Run the repository-local CLI without network access or secrets.
- Enforce dependency and distribution boundaries in local and CI gates.
- Establish the `develop -> main` release-review path.

## Offline Analysis Preview — next

- Define exchange-aware instruments, currencies, sessions, and timezone-aware observations.
- Reject ambiguous symbols and naive timestamps at public boundaries.
- Document adjustment and as-of semantics before accepting historical data.
- Add licensed-for-repository synthetic daily fixtures for Japanese and U.S. equities.
- Implement SMA20 and an explainable close-versus-SMA20 state-change signal.
- Expose the complete synthetic-data-to-evidence path through an offline demo command.

The preview validates the first data-kind-specific source contract with its synthetic implementation
and tests. It does not publish file or network adapters.

## 0.1.0 candidate

- Add historical replay that prevents future-information leakage.
- Generate channel-neutral template reports with evidence references.
- Deliver reports through a console adapter.

Completion of this path creates the first `0.1.0` release candidate. Promotion from `develop` to
`main` remains a human release decision.

## External source expansion

- Add a CSV daily-bar adapter as the first file-backed extension.
- Add J-Quants and Alpha Vantage daily-bar adapters independently after reviewing authentication,
  plans, terms, coverage, rate limits, and redistribution constraints.
- Keep each provider in a separate adapter and distribution with its own dependencies and tests.
- Add application-owned source selection and narrowly classified fallback only after at least two
  implementations establish the need.

## Personal operation

- Persist operational state and delivery receipts independently from structured logs.
- Add SMTP email delivery, followed by LINE Messaging API delivery.
- Add schedules as external interfaces into the same application pipeline.

## Assisted reporting

- Publish a report-agent port with the first template and LLM implementations.
- Give report agents validated facts rather than raw authority over calculations or alert decisions.
- Store model, prompt, input, output, and evidence provenance without exposing secrets or recipients.
