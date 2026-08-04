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

The JSON projection conforms to `schemas/capabilities-result/v1/schema.json` and describes actual
commands, options, defaults, output schemas, exit codes, streams, and operational side effects.

## Output and failure contract

`auto` selects Rich output for a TTY and ANSI-free text otherwise. `rich` uses terminal panels and
tables, `text` is line-oriented, and `json` is deterministic and schema-valid. Successful results
use stdout. User-facing failures use stderr and conform to `schemas/cli-error/v1/schema.json` in
JSON mode.

Exit code 0 means success, 1 means a runtime, data, or contract error, and 2 means invalid command
usage. The commands perform no network requests, read no secrets, and create no operational state
unless log-file output is explicitly requested.
