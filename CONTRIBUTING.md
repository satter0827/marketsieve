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

Normal pull requests are squash-merged by automation after `Develop Gate` and `Review Gate` succeed
and unresolved conversations are closed. A human decision is required only when a finding depends
on product meaning or another non-automatable tradeoff. Direct pushes to `develop` and `main` are
not part of the normal workflow.

Open a `develop -> main` pull request to promote a release candidate. `Release Gate` verifies the
source branch, supported Python versions, and public distribution. Release pull requests use merge
commits so the promotion boundary remains visible.

`make review` runs the local development checks and creates an AI-first, human-readable review
bundle. CI retains the bundle for 30 days. The machine-readable `review.json` is authoritative;
`summary.md` is a deterministic projection for reviewers.

Before opening a pull request, finish focused checks, run `make review`, and inspect the resulting
bundle once against the final diff. Open the pull request only after deterministic findings are
resolved. CI then verifies the same contracts; post-CI review addresses only new evidence or human
judgment so an unchanged concern is not recycled through repeated repair loops.

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
