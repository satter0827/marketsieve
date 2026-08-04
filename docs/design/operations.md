# Operations

## Supported current operation

MarketSieve currently supports local development, public SDK builds, version reporting, offline
diagnostics, and historical synthetic-data reports on Python 3.12 through 3.14. Python 3.13 is the
primary development version.

```shell
make sync
uv run marketsieve --version
make doctor
make report
make report-json
make capabilities-json
make build
```

These operations require no secrets, provider accounts, network data, database, scheduler, or
delivery configuration. The application does not persist operational state.

Project-local caches and generated artifacts are rooted at `.marketsieve`. The `.venv` directory is
the only repository-root development environment. Human, agent, editor, and CI workflows use the
Makefile entry points so their commands do not drift.

`make governance-check` is an authenticated, read-only maintenance command that compares active
GitHub rulesets with `.github/rulesets`. It runs with host access after a ruleset change and before
a release promotion; it is not part of the offline development gate. A mismatch blocks governance
changes and release promotion until the checked-in policy and active repository setting agree.

`make review-attest REVIEWED_SHA=<full-commit-sha>` is the only review-stage write. Run it after the
final semantic review with GitHub network access. It publishes a success status only when the named
SHA is the clean local HEAD and its evidence bundle validates.

Application output is written to stdout and user-facing errors to stderr. Structured JSON Lines logs
are written to stderr only when `--log-level` selects `DEBUG`, `INFO`, `WARNING`, or `ERROR`.
`--log-file` additionally stores records under `.marketsieve/logs/`; no log file is created unless
that option is present. The application composition root configures logging and injects a standard
library logger into application services.

Develop evidence, review bundles, and release candidates are stored below
`.marketsieve/artifacts/`. `review.json` is the review authority, while `summary.md` is generated
from it for human reading. Logs and schemas exclude credentials, recipients, portfolio data, and
unbounded exception dumps.

## Historical report operation

The deterministic report is backed only by repository-owned synthetic fixtures. It remains runnable
after dependency installation without external accounts or live services:

```shell
make report
make report-json
make capabilities-json
```

Generated command output is ephemeral and is not committed as a report or fixture. Interactive
terminals receive Rich output, while redirection receives ANSI-free text. JSON output is selected
explicitly for machine consumers.

Failures identify whether input validation, analysis prerequisites, or an internal contract caused
the operation to stop. They do not expose environment secrets or silently switch data sources.

## Unsupported operation

Live-data acquisition, scheduled execution, persistent state, non-console delivery, provider
fallback, and LLM-assisted reporting are not supported operations. When later milestones introduce them,
their configuration, recovery, observability, and secret-handling procedures must be added here in
the same change.
