# Lifecycle

## Activity classes

| Activity | Owner | Completion evidence |
| --- | --- | --- |
| Maintain constituent assets | Maintainer | source URL, as-of date, count, and asset hash |
| Build Market Snapshot | Automated | request fingerprint, source version, coverage, failures, verified object |
| Read or filter saved market data | Human or external agent | exact Snapshot ID and canonical JSONL |
| Build Security Research Pack | Automated | selected Snapshot security, source response, quality, verified object |
| Interpret evidence | Human or external agent | claims trace to Snapshot or Research Pack files |
| Adopt an investment conclusion | Human decision | outside MarketSieve canonical state |
| Place an order or send a message | Unsupported | no product path exists |

## Development and release

Work starts from `develop` on a `codex/` branch. The complete local gate and review evidence freeze a
specific SHA before CI. A reviewed change is squash-merged to `develop`. Promotion from `develop` to
`main` uses the Release Gate and a merge commit. Tags and public releases are separate decisions.

## Data and analysis lifecycle

1. Versioned assets define index memberships and fixed benchmarks.
2. One yfinance request acquires broad prices, profiles, financials, and exact failures.
3. Pure calculations create common fields and benchmark-relative measures.
4. Canonical JSONL, definitions, market context, segments, quality, and failures define the Snapshot.
5. CSV, HTML, and Markdown projections are generated and verified.
6. An analyst or agent filters the Snapshot and selects a security.
7. A focused yfinance request creates an immutable Research Pack for that Snapshot security.
8. External interpretations stay outside both objects. Later acquisition creates new objects.

Interrupted Snapshot runs live separately from completed objects. Research builds publish only
complete objects. Current commands do not load pre-0.11 market object schemas. Decision reports and
watchlists retain their isolated storage roots.

## Documentation lifecycle

Implemented contracts live in `docs/design`. Planned outcomes live in `docs/roadmap.md`. Dated notes
are temporary investigation and never become prerequisites. Root README files remain concise guides.
