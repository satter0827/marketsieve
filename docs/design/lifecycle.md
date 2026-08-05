# Lifecycle

MarketSieve defaults deterministic development work to automation and reserves human involvement
for product judgment, external authority, and release promotion.

## Activity classes

- **Automated:** AI agents, repository code, tests, or CI can complete and verify the activity.
- **Human decision:** A person must accept a tradeoff, legal meaning, risk, or release boundary.
- **Manual procedure:** A person must interact with an external identity, secret, account, or system
  that automation is not authorized to control.

Human work is not hidden inside automated instructions. Every manual procedure records an owner,
trigger, required input, completion condition, and retained evidence.

## Development and release

| Activity | Class | Completion evidence |
|---|---|---|
| Inspect current code and formal design | Automated | Relevant sources and constraints are identified |
| Convert approved requirements into code, tests, and documentation | Automated | Focused diff with matching behavior and prose |
| Run format, lint, type, test, and package gates | Automated | Successful command and CI results |
| Prepare and merge a focused pull request to `develop` | Automated | Pre-PR review, Develop Gate, and Evidence Gate pass, with no unresolved human judgment |
| Correct deterministic review or CI findings | Automated | Finding resolved and affected checks rerun |
| Resolve ambiguous market meaning or product tradeoffs | Human decision | Decision recorded in formal design or roadmap |
| Assess provider terms, licensing, and redistribution | Human decision | Approved scope and evidence of terms review |
| Supply provider accounts, credentials, or recipient identities | Manual procedure | Secret configured outside the repository and smoke-tested |
| Resolve review findings requiring judgment | Human decision | Conversation resolved with recorded rationale |
| Promote `develop` to `main` | Human decision | Human-reviewed release pull request and successful Release Gate |

Normal implementation branches start from `develop` and target `develop`. Automated integration may
proceed after required gates pass and no unresolved human judgment remains. Automation does not
decide or merge the `develop -> main` release promotion.

Review order is deterministic: focused checks, the complete local gate, evidence-bundle creation,
semantic review of the final diff, finding correction, final commit creation, commit-bound review
attestation, and then pull-request CI for the frozen commit. The ruleset requires `Pre-PR Review` for
the current head, so any code change invalidates the attestation and returns the work to the pre-PR
sequence. No asynchronous code review begins after CI. An environment-only failure may rerun the
unchanged commit after diagnosis. A reviewer does not reopen an unchanged concern; a later repair
cycle requires changed evidence or an explicitly recorded human decision.

## Documentation lifecycle

Approved current behavior and near-term constraints enter `docs/design`. Planned outcomes enter the
roadmap. Investigation begins as a dated note only when it is useful beyond a pull request. Once a
decision is accepted, the implementation change updates formal design and deletes or reduces the
note so that it cannot become a competing authority.

## Approved provider and model lifecycle

| Activity | Class | Completion evidence |
|---|---|---|
| Implement a provider from approved semantics | Automated | Contract tests, offline fixtures, and package evidence pass |
| Review provider plans, terms, and raw-response retention | Human decision | Approved capabilities and retention policy are recorded |
| Supply a provider or model credential | Manual procedure | Environment variable is configured outside the repository and a live smoke test succeeds |
| Fetch a live snapshot | Manual procedure | User explicitly selects the source profile and retains the snapshot identity |
| Render through a test-local model | Automated | Grounding, safety, and fallback tests pass without network access |
| Send facts to a cloud model | Human decision | The user supplies `--allow-cloud` after reviewing the dry-run payload |
| Change an indicator definition | Human decision | A new definition version and migration impact are approved |
| Publish a GitHub Release | Human decision | Human-approved main commit and verified wheelhouse evidence are retained |
| Configure PyPI Trusted Publishers | Manual procedure | Every catalog distribution trusts the repository workflow and protected `pypi` environment |
| Publish catalog distributions | Human decision | Existing tag, successful matching main CI run, environment approval, PyPI OIDC records, and GitHub Release |

Provider code never decides to weaken a request, switch destination, merge values, or retain raw
responses beyond its approved policy. A source or model change returns through the same focused
checks, full gate, evidence, semantic review, and commit-bound attestation sequence as core changes.

## 0.4.0 through 0.7.0 integration sequence

Each focused branch starts from the latest `develop`, passes local evidence and commit-bound review,
and enters `develop` through a squash pull request. The 0.4.0, 0.5.0, and 0.6.0 versions are
integration milestones and are not promoted to `main`, tagged, or published. After 0.7.0 is
complete, one `develop -> main` release pull request runs the Release Gate and stops for human
review. Automation does not merge that pull request, create the tag, publish a GitHub Release, or
publish to PyPI.

After a human merges the release pull request, the `main` push CI must succeed before a stable tag
is created at that exact commit. A maintainer then manually dispatches `publish.yml` with the tag
and the successful CI run ID. The protected `pypi` environment supplies approval, while PyPI trusts
that workflow and environment through OIDC. No repository or environment stores a long-lived PyPI
token.
