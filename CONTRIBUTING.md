# Contributing

## Development setup

MarketSieve requires Python 3.12 through 3.14 and uses Python 3.13 as the primary development
version.

```shell
make sync
make check
```

## Branch workflow

Create short-lived branches from `develop` and open pull requests back to `develop`. Use a focused
name such as `feature/instrument-model`, `fix/invalid-timezone`, or `docs/market-semantics`.
Repository coding agents use their required agent-specific prefix.

Normal pull requests are squash-merged by automation after `Develop Gate` and `Evidence Gate` succeed
and unresolved conversations are closed. A human decision is required only when a finding depends
on product meaning or another non-automatable tradeoff. Direct pushes to `develop` and `main` are
not part of the normal workflow.

Open a `develop -> main` pull request to promote a release candidate. `Release Gate` verifies the
source branch, supported Python versions, and public distribution. Release pull requests use merge
commits so the promotion boundary remains visible.

`make evidence` runs the local development checks and creates an AI-first, human-readable review
bundle. CI retains the bundle for 30 days. The bundle is input to code review rather than evidence
that code review occurred. The machine-readable `review.json` is authoritative; `summary.md` is a
deterministic projection for reviewers.

Before opening a pull request, finish focused checks, run `make evidence`, and review the final diff
with `codex review --base origin/develop`. Resolve the findings as one batch, rerun affected checks
and the complete gate, and freeze the reviewed commit. After a clean review, publish the commit-bound
status with `make review-attest REVIEWED_SHA=<full-commit-sha>`. The command rejects a different or
dirty HEAD and invalid evidence. CI verifies that exact commit; do not start a new asynchronous code
review after CI begins. A code change returns the work to the pre-PR review sequence instead of
extending the same CI repair loop. An environment-only failure may rerun the unchanged commit after
its cause is identified.

## Change expectations

- Keep each pull request focused on one behavior or repository concern.
- Change public behavior together with tests and relevant documentation.
- Follow the [documentation authority and change policy](docs/README.md).
- Describe implemented behavior in the present tense, approved next-milestone constraints under an
  explicit target heading, and other planned behavior only in the roadmap.
- Keep temporary investigation in dated `docs/notes` files and promote accepted decisions into the
  formal design or roadmap.
- Do not add placeholder abstractions without a working implementation.
- Do not commit credentials, recipient identifiers, live portfolio data, caches, or generated
  reports.

## Release policy

The Foundation is not a release. The first tag and GitHub Release will be `0.1.0` after the offline
analysis path is complete. Only the `marketsieve` wheel and source distribution are public release
artifacts; the repository-local application is never uploaded.
