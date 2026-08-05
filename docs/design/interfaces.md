# Interfaces

Interfaces expose application use cases and translate external input and output. They do not define
market rules, source policy, or report facts.

## Root command

```shell
uv run marketsieve
uv run marketsieve --version
```

With no subcommand, an interactive terminal shows the project purpose and quick-start commands. A
non-interactive stream receives an ANSI-free text projection. `--version` reports the installed SDK
version.

The root accepts `--locale {ja,en}`, `--log-level {DEBUG,INFO,WARNING,ERROR}`, and `--log-file`. Japanese
is the default human locale. Structured JSON Lines
logs are emitted to stderr only when a log level is requested and are additionally written below
`.marketsieve/logs/` when requested. Normal user-facing output never contains structured logs.

## Diagnostics

```shell
uv run marketsieve doctor --output {auto,rich,text,json}
```

Diagnostics check the supported Python version and installed SDK and application packages. A
failure includes a recovery action. JSON output conforms to `schemas/doctor-result/v1/schema.json`.

## Equity workbench

```shell
uv run marketsieve inspect MIC:SYMBOL --source-profile PROFILE
uv run marketsieve compare MIC:SYMBOL MIC:SYMBOL --source-profile PROFILE
uv run marketsieve equity-report MIC:SYMBOL --source-profile PROFILE --format {rich,text,json}
```

These commands use only verified local snapshots. `inspect` exposes all independent sections,
`compare` reports comparability without ranking, and `equity-report` projects the same section facts. JSON
output conforms to inspect v2, comparison v1, and report v2 schemas. Partial data is successful
when completeness and missing reasons are explicit.

## Capability discovery

```shell
uv run marketsieve capabilities --output {auto,rich,text,json}
```

The JSON projection conforms to `schemas/capabilities-result/v2/schema.json` and describes actual
commands, options, defaults, output schemas, exit codes, streams, and operational side effects.

## Output and failure contract

`auto` selects Rich output for a TTY and ANSI-free text otherwise. `rich` uses terminal panels and
tables, `text` is line-oriented, and `json` is deterministic and schema-valid. Successful results
use stdout. User-facing failures use stderr and conform to `schemas/cli-error/v1/schema.json` in
JSON mode.

Exit code 0 means success, 1 means a runtime, data, or contract error, and 2 means invalid command
usage. Read commands perform no network requests. `source fetch` explicitly reads its selected
provider credential and writes a snapshot; log-file output is the other opt-in state change.

## CLI contract

The public `marketsieve-cli` distribution owns the executable application. Human output defaults
to Japanese and supports `--locale {ja,en}`. JSON keys, schema identifiers, error codes, and enum
values remain English.

```shell
marketsieve source list
marketsieve source doctor SOURCE_PROFILE
marketsieve source fetch SOURCE_PROFILE MIC:SYMBOL --start DATE --end DATE
marketsieve source import PATH
marketsieve snapshot list
marketsieve snapshot show ID
marketsieve snapshot verify ID
marketsieve inspect MIC:SYMBOL --source-profile PROFILE
marketsieve analyze INDICATOR MIC:SYMBOL --source-profile PROFILE
marketsieve compare MIC:SYMBOL MIC:SYMBOL --source-profile PROFILE
marketsieve equity-report MIC:SYMBOL --source-profile PROFILE
```

Only fetch and import commands may create source snapshots. Read commands never perform network
access and explain the required acquisition command when no suitable snapshot exists. `inspect`
projects independent sections; `analyze` exposes the approved indicator catalog and parameters;
`compare` uses one knowledge-as-of instant; and `equity-report` is a deterministic projection of the same
facts rather than a separate analysis path.

`--config` selects an explicit configuration file, otherwise the current directory's
`marketsieve.toml` is used when present. Source profiles bind each data kind to a distribution and
entry point. Environment variables supply credentials only and do not override normal settings.

Versioned snapshot, indicator, comparison, source, report, and error schemas define machine output.
Capabilities version 2 describes actual network, secret, read, write, plugin, schema, stream, and
exit behavior. Partial results are successful only when their completeness and missing reasons are
explicit.

### Implemented CSV and section composition

`source list`, `source import`, `snapshot list`, `snapshot show`, `snapshot verify`, and `inspect`
are implemented for daily-bar CSV snapshots. Import is the only CSV command that writes market-data
state. `inspect` composes price, technical, financial, valuation, risk, event, and data-quality
sections. Missing values remain unavailable and are never represented as zero values.
The financial section includes the selected current and preceding compatible annual periods under
`history` and deterministic derived metrics under `derived`. Its explicit `as_of` is the knowledge
instant; observations available later are excluded.

### Implemented indicator commands

```shell
marketsieve analyze sma MIC:SYMBOL --period 20 --source-profile PROFILE
marketsieve analyze ema MIC:SYMBOL --period 20 --source-profile PROFILE
marketsieve analyze rsi MIC:SYMBOL --period 14 --source-profile PROFILE
marketsieve analyze macd MIC:SYMBOL --fast-period 12 --slow-period 26 --signal-period 9 --source-profile PROFILE
marketsieve analyze atr MIC:SYMBOL --period 14 --source-profile PROFILE
marketsieve analyze period-return MIC:SYMBOL --period 20 --source-profile PROFILE
marketsieve analyze maximum-drawdown MIC:SYMBOL --period 252 --source-profile PROFILE
```

These commands read one verified snapshot and never fetch. JSON output conforms to
`schemas/indicator-result/v1/schema.json`. Insufficient history is a successful result with an
empty `values` object and explicit status. Invalid periods, extra parameters, and invalid MACD
period ordering are errors.

### Implemented J-Quants commands

```shell
marketsieve --config marketsieve.toml source doctor japan
marketsieve --config marketsieve.toml source doctor japan --kind financials
marketsieve --config marketsieve.toml source fetch japan XTKS:7203 \
  --start 2026-01-01 --end 2026-07-31 --adjustment adjusted
marketsieve --config marketsieve.toml source fetch japan XTKS:7203 \
  --start 2026-01-01 --end 2026-07-31 --kind financials
marketsieve --config marketsieve.toml source fetch japan XTKS:7203 \
  --start 2026-01-01 --end 2026-07-31 --kind events
```

`source doctor` validates only the selected profile, plugin settings, and credential presence; it
does not contact J-Quants. `source fetch` is the only J-Quants command that uses the network and it
stores one immutable normalized snapshot per selected data kind. Configuration does not supply or
override credentials. Financials use `/fins/summary`. Event settings explicitly select `earnings`
and optionally `dividend`; unselected or unavailable endpoints are not called automatically. An
unavailable provider plan, excessive exact request, or rate limit is an explicit failure rather
than a shortened or substituted success.

### Implemented Alpha Vantage commands

The same `source doctor` and `source fetch` commands accept an Alpha Vantage profile for XNAS and
XNYS instruments. `ALPHAVANTAGE_API_KEY` is the only credential input. Daily settings explicitly
declare `plan` and `outputsize`; adjusted or full-history requests reject a free plan before network
access. Event settings explicitly select earnings, dividend, and/or split endpoints. Provider
errors, compact coverage gaps, and rate limits fail without retry, range shortening, or fallback.
For Alpha Vantage financial statements, `--start` and `--end` filter the provider's
`fiscalDateEnding`; they do not imply that the fact was published inside that range. Earnings,
dividend, and split events are filtered by their provider-reported event dates. All values without
a publication timestamp remain retrieval-bounded for knowledge-as-of use.

### Implemented FRED extension

The installed-source catalog reports FRED's `economic_series` capability without importing plugin
code. Adapter users can load the explicitly selected entry point and call `EconomicSeriesFetcher`
with a series ID, observation range, and knowledge date. The adapter has no CLI fetch route or
implicit persistence yet; Personal Close Brief orchestration adds those application concerns.

### Implemented SEC commands

The same `source doctor` and `source fetch --kind financials` commands accept an SEC profile for
XNAS and XNYS instruments. The profile supplies a ten-digit `cik`; `SEC_USER_AGENT` supplies the
organization and contact email required for network access. `doctor` validates both without making
a request. `--start` and `--end` select filing dates, and the stored facts retain the exact SEC
acceptance time for knowledge-as-of use.

### Implemented EDINET commands

The same `source doctor` and `source fetch --kind financials` commands accept an EDINET profile for
XTKS instruments. The profile supplies an `edinet_code`, supported document type codes, and explicit
date and document budgets. `EDINET_API_KEY` is the only credential input. `doctor` validates the
profile and credential presence without a request. Fetch creates filing-linked financial snapshots
from official XBRL-derived TSV data and never performs ticker-to-issuer lookup.

## Agent explanation

```shell
marketsieve agent doctor lmstudio
marketsieve report explain {ID,latest} --provider lmstudio
marketsieve report explain {ID,latest} --provider openai --allow-cloud
marketsieve report explain {ID,latest} --provider anthropic --allow-cloud
marketsieve report explain {ID,latest} --provider google --allow-cloud
marketsieve report explain {ID,latest} --provider openai --dry-run
```

There is no default provider. Model names are explicit configuration and are not frozen in source
code. Dry-run shows the credential-free outgoing report payload. Unsafe, invalid, or unavailable model
output produces a warning on stderr and a deterministic template on stdout. No provider failure
changes the selected report. Successful and template explanations are immutable artifacts below
`.marketsieve/explanations`; report objects remain unchanged.

`agent doctor PROVIDER` validates configuration without contacting a model. LM Studio endpoints are
loopback-only unless `--allow-remote` is explicit. Provider model names and the optional LM Studio
endpoint are read from `[agent.providers.NAME]`; credentials are never valid TOML settings.

## 0.4.0 routine CLI target

Routine operation uses the following commands:

```shell
marketsieve init
marketsieve portfolio import --broker rakuten PATH
marketsieve portfolio show
marketsieve daily {jp,us}
marketsieve weekly
marketsieve report list
marketsieve report show {ID,latest}
marketsieve report export {ID,latest} --format markdown
marketsieve report explain {ID,latest} --provider PROVIDER
```

The implemented broker-neutral path is:

```shell
marketsieve portfolio import --broker canonical --as-of TIMESTAMP PATH
marketsieve portfolio show
```

Canonical CSV uses the exact header
`kind,mic,symbol,currency,timezone,quantity,average_acquisition_price,account_type`.
`holding` rows require positive quantity, acquisition price, and a non-empty account type. `watch`
rows require those three fields to be empty. Instruments are equities identified by MIC, symbol,
currency, and IANA timezone. Normalized holdings and watch items use a stable instrument order.

`daily` explicitly acquires price, financial, and event data through the configured profile,
validates each snapshot, and evaluates every held or watched instrument in the selected market.
Price failure makes that instrument indeterminate. Financial or event failure leaves the price
decision usable, records the missing evidence, and cannot silently reuse another provider. If every
instrument is indeterminate, the command fails and does not update the latest reference.

`weekly` reads the latest eligible Japanese and U.S. reports and performs no network access. A
missing or stale input names the daily command required to recover. `report show` and `report
export` are read-only. `report explain` contacts only the explicitly selected model and stores an
explanation separately from the report.

`decision-report/v1` records `input_report_ids`. The field is empty for daily reports and contains
exactly the sorted Japanese and U.S. report IDs for a weekly report. The default weekly eligibility
window is seven days. `[routines.weekly].max_age_days` can set an integer from 1 through 14.

Human output presents conclusion, attention items, changes, unchanged items, next action, data
limitations, and detailed evidence in that order. `--quiet` retains the conclusion, attention
items, and next action. JSON returns the canonical English-keyed decision-report contract without
localized decorative prose.

The change section compares action and confidence against the exact `previous_report_id` object.
It marks a newly reviewed instrument as new and a removed instrument as outside the current target.
The unchanged section contains only instruments whose action and confidence both remain equal.

Advanced acquisition and inspection commands move below `marketsieve data`. Their semantics remain
available, but the old top-level command paths are not preserved.
