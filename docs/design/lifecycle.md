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
| Prepare and merge a focused pull request to `develop` | Automated | Develop and Review Gates pass, with no unresolved human judgment |
| Correct deterministic review or CI findings | Automated | Finding resolved and affected checks rerun |
| Resolve ambiguous market meaning or product tradeoffs | Human decision | Decision recorded in formal design or roadmap |
| Assess provider terms, licensing, and redistribution | Human decision | Approved scope and evidence of terms review |
| Supply provider accounts, credentials, or recipient identities | Manual procedure | Secret configured outside the repository and smoke-tested |
| Resolve review findings requiring judgment | Human decision | Conversation resolved with recorded rationale |
| Promote `develop` to `main` | Human decision | Human-reviewed release pull request and successful Release Gate |

Normal implementation branches start from `develop` and target `develop`. Automated integration may
proceed after required gates pass and no unresolved human judgment remains. Automation does not
decide or merge the `develop -> main` release promotion.

## Documentation lifecycle

Approved current behavior and near-term constraints enter `docs/design`. Planned outcomes enter the
roadmap. Investigation begins as a dated note only when it is useful beyond a pull request. Once a
decision is accepted, the implementation change updates formal design and deletes or reduces the
note so that it cannot become a competing authority.
