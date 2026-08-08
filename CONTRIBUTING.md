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

Normal pull requests are squash-merged by automation after `Develop Gate` and `Semantic Review` succeed
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

Before opening a pull request, finish focused checks and create the draft PR so Static, Tests, and
Package can run in parallel. Review the full diff once. After changes, create a delta bundle with
`make evidence PREVIOUS_REVIEWED_SHA=<full-commit-sha>` and review only that proven descendant.
Conflict resolution or history replacement that breaks ancestry returns review to the full PR diff.
After a clean review, publish `Semantic Review` with
`make review-attest REVIEWED_SHA=<full-commit-sha>`. CI tests GitHub's virtual merge result without
rewriting the feature branch. The attestation command rejects a different or dirty HEAD and invalid
evidence.

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

`0.1.0` is the first stable release. Starting with the 0.2 development line, `marketsieve` and
`marketsieve-cli` are independently built public distributions and retain the same version. Release
artifacts are published through GitHub Releases only. PyPI publication remains disabled until
Trusted Publishing has a separate approved design.
