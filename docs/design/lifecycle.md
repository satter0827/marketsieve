# Lifecycle

## Activity classes

- **Automated:** repository code, tests, or CI can complete and verify the activity.
- **Human decision:** product meaning, external terms, or release approval requires a person.
- **Manual procedure:** a person supplies local input or performs an external operation whose state
  is not owned by MarketSieve.

## Development and release

| Activity | Class | Completion evidence |
| --- | --- | --- |
| Implement a focused change | Automated | Focused tests and the complete local gate pass |
| Review the frozen commit | Human decision | Semantic review has no unresolved finding |
| Attest the reviewed commit | Automated | Commit-bound review status matches clean HEAD |
| Merge a develop pull request | Automated | Develop Gate and Evidence Gate succeed |
| Promote develop to main | Human decision | Release Gate succeeds and a person approves the boundary |
| Publish a tag or package | Human decision | Separate release procedure is explicitly authorized |

A code change after review returns to local checks, evidence, semantic review, and attestation. CI
does not become an iterative code-review loop.

## Data and analysis lifecycle

| Activity | Class | Completion evidence |
| --- | --- | --- |
| Import a portfolio export | Manual procedure | Immutable normalized holdings object verifies |
| Add or remove a watchlist instrument | Human decision | New content-addressed revision names the change |
| Fetch a bounded market universe | Manual procedure | Universe identity, truncation, and diagnostics persist |
| Run deterministic screening | Automated | Static screening report verifies |
| Promote a candidate to watchlist | Human decision | Explicit command records screening provenance |
| Build an analysis workspace | Automated | Context ID and Markdown verify from the same artifacts |
| Research news and discuss a decision | Human decision | Work remains external to canonical MarketSieve state |

Provider code never weakens a request, switches destination, merges values, or retains raw
responses beyond its approved contract. A provider change uses the same focused checks and review
sequence as core changes.

## Documentation lifecycle

Tested behavior and public types are executable authority. Formal design describes implemented
system behavior. The roadmap orders later outcomes. Temporary notes never become prerequisites for
understanding the current contract.
