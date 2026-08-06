# Operations

## Supported current operation

MarketSieve currently supports local development, public distribution builds, offline analysis,
immutable CSV snapshots, explicit J-Quants price, financial-summary, dividend, and earnings
acquisition, and explicit Alpha Vantage price, profile, financial-statement, earnings, dividend,
and split acquisition. It also builds and discovers independently installable FRED economic-series
plus SEC and EDINET filing adapters on Python 3.12 through 3.14. Python 3.13 is the primary
development version. The `daily jp` and `daily us` routines explicitly acquire configured price
history, official financial facts, and corporate events, evaluate the latest local portfolio, and
persist an immutable Close Brief.

```shell
make sync
uv run marketsieve --version
make doctor
make capabilities-json
make build
```

The listed development operations require no secrets or provider accounts.
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

## Decision report operation

Stored decision reports are read and exported without contacting a provider:

```shell
uv run marketsieve report list --output json
uv run marketsieve report show latest --output json
uv run marketsieve report export latest --format markdown
```

The list command succeeds with an empty result when no report exists. Show and export require an
existing verified report. Interactive terminals receive Rich output, while redirection receives
ANSI-free text. JSON output is selected explicitly for machine consumers.

The decision-report adapter stores canonical JSON below `.marketsieve/reports/objects`, generated
Markdown below `.marketsieve/reports/rendered`, and atomic per-session latest references below
`.marketsieve/reports/refs`. An all-indeterminate report is retained for diagnosis but never
replaces a usable latest reference. Daily routines use this store directly.

Daily source selection is explicit and non-secret:

```toml
[routines.jp]
source_profile = "japan"
lookback_days = 400
financial_lookback_days = 1500

[routines.us]
source_profile = "united-states"
lookback_days = 400
financial_lookback_days = 1500

[routines.weekly]
max_age_days = 7
```

`lookback_days` accepts 60 through 2,000 calendar days and defaults to 400. The routine uses the
selected source profile for every instrument in that market and does not fall back to another
provider. `financial_lookback_days` accepts 365 through 4,000 calendar days and defaults to 1,500.
The routine also fetches events from 30 days before through 30 days after the market-local analysis
date. Facts and events unavailable at `--as-of` are excluded even when the snapshot was retrieved
later. Financial and event failures remain explicit optional-evidence diagnostics; price failure
makes the instrument indeterminate. `--as-of` accepts an explicit offset-aware timestamp for
reproducible operation; without it, the CLI uses the invocation time.

`marketsieve weekly` is offline. It combines only the current `jp-latest` and `us-latest` reports
when neither is future-dated or older than the configured limit. It never refreshes data or
recalculates daily decisions. A missing or stale side returns the exact daily command needed before
the weekend briefing can be created.

Failures identify whether input validation, analysis prerequisites, or an internal contract caused
the operation to stop. They do not expose environment secrets or silently switch data sources.

Strategy Lab specifications identify immutable local daily-bar snapshots directly:

```toml
[experiment]
start = "2025-01-01"
end = "2025-12-31"

[experiment.datasets]
"XTKS:7203" = "<snapshot_sha256>"
```

`marketsieve experiment run strategy.toml` performs no acquisition. Runs are stored below
`.marketsieve/experiments/objects`. Execution costs are optional, but commission, tax, and FX rates
must be supplied together; no net-profit metric is calculated in the current implementation.
`marketsieve experiment explain RUN_ID --provider PROVIDER` is the only Strategy Lab command that
may contact a model. It stores the exact credential-free prompt, selected provider and model
settings, raw model output, validation result, and deterministic fact rendering separately below
`.marketsieve/experiments/explanations`. It never rewrites an experiment run.

## Unsupported operation

Scheduled execution, non-console delivery, provider fallback, and LLM-generated calculations are not
supported operations. When later milestones introduce them,
their configuration, recovery, observability, and secret-handling procedures must be added here in
the same change.

## Data workbench operation

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

FRED uses only `https://api.stlouisfed.org/fred/series/observations` and reads `FRED_API_KEY` from
the invoking environment. The official contract reviewed on 2026-08-06 requires a 32-character
lowercase alphanumeric API key, supports explicit real-time and observation bounds, permits up to
100,000 observations per page, and reports throttling with HTTP 429. The adapter sends one exact
historical knowledge date as both real-time bounds and uses `output_type=1`, `units=lin`, and
ascending observation order. It neither retries rate limits nor stores raw responses. The
[official endpoint contract](https://fred.stlouisfed.org/docs/api/fred/series_observations.html)
is rechecked before a release or request-policy change.

SEC uses only `https://data.sec.gov/submissions` and
`https://data.sec.gov/api/xbrl/companyfacts`. It requires no API key. The profile declares a
ten-digit CIK, while `SEC_USER_AGENT` supplies the organization and contact email required by SEC
fair-access policy. The adapter stays below the published maximum of ten requests per second by
making sequential bounded requests and leaves retry scheduling to the application. Official API
and fair-access documentation were reviewed on 2026-08-06 and are rechecked before a release or
request-policy change. See the
[official EDGAR data API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
and the
[fair-access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data).

EDINET uses only `https://api.edinet-fsa.go.jp/api/v2/documents.json` and
`https://api.edinet-fsa.go.jp/api/v2/documents/{docID}`. It reads `EDINET_API_KEY` from the invoking
environment and sends it only as `Subscription-Key`. Historical list requests are sequential and
bounded to 31 dates and 100 selected documents. The adapter uses official type 5 ZIP files, which
contain XBRL-derived UTF-16 tab-separated values, and does not retain the archive. The official
[EDINET API v2 specification](https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/download/ESE140206.pdf)
and [operation guide](https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/WZEK0110.html)
were reviewed on 2026-08-06 and are rechecked before a release or request-policy change.

Content-addressed objects are written to a temporary sibling directory, verified, and atomically
renamed. Raw responses are retained only when the adapter's approved terms policy permits local
retention and its redaction step succeeds. Mutable references can be rebuilt from verified object
manifests.

Release evidence contains every wheel and source distribution, a wheelhouse archive, constraints,
a SHA-256 manifest, and compatibility results. The build-once job includes locked runtime wheels
for Python 3.12, 3.13, and 3.14 on the release runner platform; every compatibility job verifies
and installs that same checksummed artifact without regenerating dependencies. The approved
publish workflow creates a draft GitHub Release, uploads catalog-owned distributions through PyPI
Trusted Publishing, and publishes the GitHub Release only after PyPI succeeds. A failure leaves a
recoverable draft instead of presenting a partially completed release as final.

## Model operation

Daily AI use starts with `make daily-jp-ai`, `make daily-us-ai`, `make weekly-ai`, or
`make ai-prepare`. The first two acquire market data over the network and prepare a request only
after report generation succeeds; weekly preparation and preparation from an existing report are
offline. The terminal prints the exact files and next command. A person then uses a new ChatGPT
Temporary Chat without Project, web search, or external tools, saves the JSON response, runs
`make ai-import RESPONSE=/absolute/path/response.json`, and reads it with `make ai-show`.
The import records controlled conditions only when the operator explicitly adds `CONTROLLED=1`;
the default does not attest chat settings.

The repository VS Code Run and Debug view presents the operational prerequisites and routine in
executable order. Launch configurations `01` through `03` create a non-secret configuration without
overwrite, import a selected portfolio CSV, and verify readiness. Configurations `10` and `20` run
the independent market-close routines, configuration `30` creates the optional weekend brief after
both daily reports, and configuration `40` imports and shows one saved response. Tasks mirror the
same Makefile operations as an alternative entry point. Missing prerequisites identify the exact
next numbered operation. Individual commands and code-debug launchers remain available after this
primary path and do not replace it.

The request, original response, validation, and explanation live in separate content-addressed
directories below `.marketsieve/ai`. They are local generated evidence and are not committed.
Temporary Chat reduces retained product history but does not remove the need to exclude private
portfolio data. Custom Instructions are disabled and that condition is recorded in the request and
validated explanation provenance. MarketSieve does not automate the ChatGPT browser or claim a
stable UI contract.
The operating assumptions follow OpenAI's
[Temporary Chat FAQ](https://help.openai.com/en/articles/8914046-temporary-chat-faq) and
[File Uploads FAQ](https://help.openai.com/en/articles/8555545-file-uploads-with-gpts-and-advanced-data-analysis-in-chatgpt)
as reviewed on 2026-08-06.

The existing direct-provider operation remains available:

The CLI has no default model. LM Studio accepts loopback endpoints by default. A cloud
provider requires explicit provider configuration and `--allow-cloud` on every invocation. Dry-run
shows the credential-free fact payload without contacting a model. Provider, model, prompt version,
fact-catalog hash, selected fact identifiers, output status, and fallback reason are recorded in a
separate content-addressed explanation artifact; API keys and unrestricted prompts are not written
to logs or report objects.

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

## Personal operation

The normal schedule is one Japanese close report after Tokyo trading, one U.S. close report after
New York trading, and one combined report on the weekend. MarketSieve provides one-shot commands;
the user owns invocation timing. A market session records its explicit as-of instant and never
assumes that a wall-clock time proves market closure.

Shareable source and policy settings remain in `marketsieve.toml`. Normalized portfolio snapshots,
reports, rendered Markdown, and mutable latest references remain below `.marketsieve` and are
ignored by version control. Source brokerage files are read once and not copied into local state.
Portfolio objects live below `.marketsieve/portfolio/objects`; `refs/latest.json` is replaced
atomically. The object contains normalized holdings and watch items plus the source digest, but no
source path, original bytes, account number, or customer name. It also retains the importer name,
importer version, dataset identity, and diagnostics needed to reproduce provenance.

Routine output is optimized for a short review. A successful report may state that no action is
needed. Warnings identify a concrete missing, stale, incompatible, or failed input and name the
next command when recovery is possible. General legal disclaimers do not replace data-quality
information.

FRED credentials enter through `FRED_API_KEY`. Rakuten import uses a local file and no credential.
The importer accepts only the fixture-proven CP932 no-holdings `assetbalance(all)` form, rejects
non-empty or structurally different detail sections, and records the input digest without retaining
the source path or contents. The committed fixture contains structural labels and zero values only.
Live portfolio data and generated reports never enter tests, evidence bundles, distributions, or
logs.
