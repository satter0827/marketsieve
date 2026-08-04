# Interfaces

Interfaces expose application use cases. They do not define domain rules or provider policy.

## Current command-line interface

```shell
uv run marketsieve --version
uv run marketsieve doctor
```

`--version` reports the installed SDK version. `doctor` checks the supported Python version and
installed SDK and application packages. Both commands are deterministic, perform no network
requests, read no secrets, and create no operational state.

The root command accepts `--log-level {DEBUG,INFO,WARNING,ERROR}` and `--log-file`. Result text is
always written to stdout. Structured JSON Lines records are written to stderr and, only when
requested, below `.marketsieve/logs/`.

The repository-local CLI is not included in the public `marketsieve` wheel.

## Current offline demo

The repository-local command is:

```shell
uv run marketsieve demo --market {jp,us,all} --format {text,json}
```

Both options default to `all` and `text`. The command uses only bundled synthetic fixtures and
accepts no provider credentials. `all` always returns JP before US. Its result contains:

- exchange-qualified instrument identity and market;
- analysis date and input date range;
- SMA20 value and current close-versus-SMA20 state;
- state-change presence and direction when one exists;
- evidence identity and input provenance;
- an explicit insufficient-history or invalid-input outcome when analysis cannot complete.

The command returns a non-zero exit status for invalid configuration, invalid fixture data, or an
internal contract violation. A valid no-signal or insufficient-history analysis is a successful
domain result and is not converted into a command failure.

JSON output conforms to `schemas/demo-result/v1/schema.json`; Decimal values are strings and
timestamps include an offset. Valid no-signal and insufficient-history results exit 0, contract or
fixture failures exit 1, and invalid Click arguments exit 2. Provider selection, fallback, live
data, and output delivery are not part of this interface.
