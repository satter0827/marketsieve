# Lifecycle

## Activity classes

| Activity | Owner | Completion evidence |
| --- | --- | --- |
| Maintain built-in constituent assets | Maintainer | source URL, as-of date, count, and asset hash review |
| Fetch yfinance observations | Automated | request fingerprint, source version, input snapshot, failures |
| Calculate and store matrix | Automated | immutable object verifies and coverage is explicit |
| List, query, read, or compare stored rows | Human or external agent | selected matrix ID and verified JSONL |
| Interpret aggregate analysis | Human or external agent | claims trace to matrix summary and definitions |
| Adopt a security-specific conclusion | Human decision | outside MarketSieve canonical state |
| Place an order or send a message | Unsupported | no product path exists |

## Development and release

Work starts from `develop` on a `codex/` branch. The complete local gate and review evidence freeze a
specific SHA before CI. A reviewed change is squash-merged to `develop`. Promotion from `develop` to
`main` uses the Release Gate and a merge commit. Tags and public releases are separate explicit
decisions.

## Data and analysis lifecycle

1. A versioned built-in asset defines the requested index memberships.
2. One yfinance batch request acquires prices, profiles, financials, and exact failure evidence.
3. Pure calculations create the common row field set and index-relative measures.
4. Canonical JSONL, definitions, manifest, summary, and failures determine the matrix identity.
5. CSV, HTML, and Markdown are generated from that authority and verified on read.
6. The matrix README and neutral summary make the directory understandable without external state.
7. External interpretations remain outside the matrix object.
8. A later refresh creates another object. It never rewrites an earlier object.

Interrupted runs live separately from completed objects. Existing pre-0.9 local artifacts remain
recoverable on disk but no current schema or command reads them. Current decision reports and
watchlists use the isolated `.marketsieve/reports/v2` and `.marketsieve/watchlists/v2` roots.

## Documentation lifecycle

Implemented system contracts live in `docs/design`. Planned outcomes live in `docs/roadmap.md`.
Dated notes are temporary investigation and never become prerequisites for understanding current
behavior. Root README files remain concise audience guides.
