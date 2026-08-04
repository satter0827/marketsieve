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

The root accepts `--log-level {DEBUG,INFO,WARNING,ERROR}` and `--log-file`. Structured JSON Lines
logs are emitted to stderr only when a log level is requested and are additionally written below
`.marketsieve/logs/` when requested. Normal user-facing output never contains structured logs.

## Diagnostics

```shell
uv run marketsieve doctor --output {auto,rich,text,json}
```

Diagnostics check the supported Python version and installed SDK and application packages. A
failure includes a recovery action. JSON output conforms to `schemas/doctor-result/v1/schema.json`.

## Historical report

```shell
uv run marketsieve report --market {jp,us,all} --output {auto,rich,text,json}
```

Both options default to `all` and `auto`. `all` always returns JP before US. The command uses only
bundled synthetic data and evaluates SMA20 at each observation's availability instant. Its report
contains the latest state, state changes, provenance, replay identity, report identity, and evidence
references. It does not express an investment recommendation.

JSON output conforms to `schemas/report-result/v1/schema.json`. Decimal values are strings and
timestamps include an offset. Insufficient history and no state changes are successful results.

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

## Approved 0.2 CLI target

The public `marketsieve-cli` distribution owns the executable application. The existing English
0.1 projections remain available while Japanese-default, `--locale {ja,en}` projections are added
with the 0.2 workbench commands. JSON keys, schema identifiers, error codes, and enum values remain
English.

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
marketsieve report MIC:SYMBOL --source-profile PROFILE
```

Only fetch and import commands may create source snapshots. Read commands never perform network
access and explain the required acquisition command when no suitable snapshot exists. `inspect`
projects independent sections; `analyze` exposes the approved indicator catalog and parameters;
`compare` uses one knowledge-as-of instant; and `report` is a deterministic projection of the same
facts rather than a separate analysis path.

`--config` selects an explicit configuration file, otherwise the current directory's
`marketsieve.toml` is used when present. Source profiles bind each data kind to a distribution and
entry point. Environment variables supply credentials only and do not override normal settings.

Versioned snapshot, indicator, comparison, source, report, and error schemas define machine output.
Capabilities version 2 describes actual network, secret, read, write, plugin, schema, stream, and
exit behavior. Partial results are successful only when their completeness and missing reasons are
explicit.

### Implemented CSV vertical slice

`source list`, `source import`, `snapshot list`, `snapshot show`, `snapshot verify`, and `inspect`
are implemented for daily-bar CSV snapshots. Import is the only command in this slice that writes
market-data state. Snapshot and inspection commands are offline. `inspect` currently returns an
available price section and explicitly unavailable technical, financial, valuation, risk, event,
and data-quality sections. It never treats those omissions as zero values.

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
marketsieve --config marketsieve.toml source fetch japan XTKS:7203 \
  --start 2026-01-01 --end 2026-07-31 --adjustment adjusted
```

`source doctor` validates only the selected profile, plugin settings, and credential presence; it
does not contact J-Quants. `source fetch` is the only J-Quants command that uses the network and it
stores one immutable normalized snapshot. Configuration does not supply or override credentials.
An unavailable provider plan, excessive exact request, or rate limit is an explicit failure rather
than a partial success.

## Approved 0.3 agent target

```shell
marketsieve agent explain MIC:SYMBOL --source-profile PROFILE --provider fake
marketsieve agent explain MIC:SYMBOL --source-profile PROFILE --provider lmstudio
marketsieve agent explain MIC:SYMBOL --source-profile PROFILE --provider openai --allow-cloud
marketsieve agent explain MIC:SYMBOL --source-profile PROFILE --provider anthropic --allow-cloud
marketsieve agent explain MIC:SYMBOL --source-profile PROFILE --provider google --allow-cloud
marketsieve agent explain MIC:SYMBOL --source-profile PROFILE --provider openai --dry-run
```

Fake is the default. Real model names are explicit configuration and are not frozen in source code.
Dry-run shows the credential-free outgoing fact payload. Unsafe, invalid, or unavailable model
output produces a warning on stderr and a deterministic template on stdout. No provider failure
changes the selected destination.
