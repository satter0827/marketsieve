# Operations

## Supported current operation

MarketSieve currently supports local development, public distribution builds, offline analysis,
immutable CSV snapshots, explicit J-Quants price, financial-summary, dividend, and earnings
acquisition, and explicit Alpha Vantage price, profile, financial-statement, earnings, dividend,
and split acquisition on Python 3.12 through 3.14. Python 3.13 is the primary development version.

```shell
make sync
uv run marketsieve --version
make doctor
make report
make report-json
make capabilities-json
make build
```

The listed development and synthetic-report operations require no secrets or provider accounts.
J-Quants fetch is a separate explicit operation that requires its environment credential and writes
an immutable snapshot below `.marketsieve/data`.

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

The decision-report adapter stores canonical JSON below `.marketsieve/reports/objects`, generated
Markdown below `.marketsieve/reports/rendered`, and atomic per-session latest references below
`.marketsieve/reports/refs`. An all-indeterminate report is retained for diagnosis but never
replaces a usable latest reference. Routine commands start using this store when the remaining
Personal Close Brief orchestration is implemented.

Failures identify whether input validation, analysis prerequisites, or an internal contract caused
the operation to stop. They do not expose environment secrets or silently switch data sources.

## Unsupported operation

Scheduled execution, non-console delivery, provider fallback, and LLM-generated calculations are not
supported operations. When later milestones introduce them,
their configuration, recovery, observability, and secret-handling procedures must be added here in
the same change.

## Approved 0.2 operation

Shareable, non-secret source profiles and analysis settings live in `marketsieve.toml`. Generated
snapshots, references, logs, caches, and artifacts live below `.marketsieve`. A source profile names
the distribution and entry point selected for each data kind. Listing installed entry-point
metadata does not load plugin code; doctor and fetch load only the selected profile.

Acquisition is explicit and may use network access and provider credentials. Inspection, analysis,
comparison, report rendering, and snapshot verification are offline. Credentials enter through
provider-specific environment variables only. MarketSieve does not load `.env` files, persist
credential values, or pass the complete parent environment to child processes.

The implemented J-Quants profile shape is:

```toml
[source_profiles.japan]
currency = "JPY"
timezone = "Asia/Tokyo"

[source_profiles.japan.daily_bars]
plugin = "jquants"

[source_profiles.japan.daily_bars.settings]
timeout_seconds = 30

[source_profiles.japan.financials]
plugin = "jquants"

[source_profiles.japan.events]
plugin = "jquants"

[source_profiles.japan.events.settings]
event_types = "earnings"
```

The API origin is fixed by the adapter to prevent credential forwarding to another host.
`JQUANTS_API_KEY` is read from the invoking process only. MarketSieve does not obtain or refresh
provider tokens, print response bodies on failure, or copy the credential into logs and snapshots.

The individual J-Quants API V2 product page,
[official Python client](https://github.com/J-Quants/jquants-api-client-python), daily-bars, instrument-master,
financial-summary, dividend, and earnings-calendar contracts, plan presentation, and terms were
reviewed on 2026-08-04. Financial summary and earnings calendar are available from Free; dividend
requires Premium according to the reviewed plan. `event_types` therefore defaults to `earnings` and
must include `dividend` explicitly before that endpoint is called. Provider plan entitlements, rate
limits, retention rights, and terms remain external policy rather than a frozen MarketSieve
contract. The adapter does not claim that a configured plan supports a range, does not retain raw
responses, and preserves HTTP authorization and limit failures for the operator. Before a release,
maintainers recheck the official [J-Quants site](https://jpx-jquants.com/) and endpoint contracts
instead of relying on fixtures as legal or commercial authority.

Alpha Vantage uses only `https://www.alphavantage.co/query` and reads
`ALPHAVANTAGE_API_KEY` from the invoking environment. Official documentation reviewed on 2026-08-04
identifies raw compact daily data as available to free and premium keys, raw full history as
premium, and daily adjusted as premium. The adapter records the configured plan rather than
probing or downgrading it. Raw responses are hashed but not persisted. Provider documentation and
terms must be rechecked before a live release test or any change to raw-storage policy.

Content-addressed objects are written to a temporary sibling directory, verified, and atomically
renamed. Raw responses are retained only when the adapter's approved terms policy permits local
retention and its redaction step succeeds. Mutable references can be rebuilt from verified object
manifests.

GitHub Release is the approved distribution channel. Release evidence contains every wheel and
source distribution, a wheelhouse archive, constraints, a SHA-256 manifest, and compatibility
results. The build-once job includes locked runtime wheels for Python 3.12, 3.13, and 3.14 on the
release runner platform; every compatibility job verifies and installs that same checksummed
artifact without regenerating dependencies. PyPI publication remains disabled, so installation uses an unpacked wheelhouse with
`pip --no-index --find-links`.

## Approved 0.3 operation

FakeListLLM remains the default model. LM Studio accepts loopback endpoints by default. A cloud
provider requires explicit provider configuration and `--allow-cloud` on every invocation. Dry-run
shows the credential-free fact payload without contacting a model. Provider, model, prompt version,
fact-catalog hash, selected fact identifiers, output status, and fallback reason are recorded; API
keys and unrestricted prompts or responses are not written to logs.

The implemented configuration contains only model destinations:

```toml
[agent.providers.lmstudio]
model = "locally-installed-model"
endpoint = "http://127.0.0.1:1234/v1"

[agent.providers.openai]
model = "explicit-cloud-model"
```

Cloud credentials are read from `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GOOGLE_API_KEY` only
after a non-dry-run invocation selects that provider. `LMSTUDIO_API_TOKEN` is optional. Dry-run and
doctor perform no model request and do not read a cloud credential.

## 0.4.0 personal operation target

The normal schedule is one Japanese close report after Tokyo trading, one U.S. close report after
New York trading, and one combined report on the weekend. MarketSieve provides one-shot commands;
the user owns invocation timing. A market session records its explicit as-of instant and never
assumes that a wall-clock time proves market closure.

Shareable source and policy settings remain in `marketsieve.toml`. Normalized portfolio snapshots,
reports, rendered Markdown, and mutable latest references remain below `.marketsieve` and are
ignored by version control. Source brokerage files are read once and not copied into local state.

Routine output is optimized for a short review. A successful report may state that no action is
needed. Warnings identify a concrete missing, stale, incompatible, or failed input and name the
next command when recovery is possible. General legal disclaimers do not replace data-quality
information.

FRED credentials enter through `FRED_API_KEY`. Rakuten import uses a local file and no credential.
The importer accepts only fixture-proven formats, drops account identifiers, and records the input
digest without retaining the file contents. Live portfolio data and generated reports never enter
tests, evidence bundles, distributions, or logs.
