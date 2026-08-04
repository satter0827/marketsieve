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

The repository-local CLI is not included in the public `marketsieve` wheel.

## Approved offline demo

The Offline Analysis Preview adds one repository-local `demo` command. It uses only bundled
synthetic fixtures and accepts no provider credentials. Its result contains:

- exchange-qualified instrument identity and market;
- analysis date and input date range;
- SMA20 value and current close-versus-SMA20 state;
- state-change presence and direction when one exists;
- evidence identity and input provenance;
- an explicit insufficient-history or invalid-input outcome when analysis cannot complete.

The command returns a non-zero exit status for invalid configuration, invalid fixture data, or an
internal contract violation. A valid no-signal or insufficient-history analysis is a successful
domain result and is not converted into a command failure.

Exact option names, serialized shapes, and public Python signatures are defined only with the
working implementation and its tests. Provider selection, fallback, live data, and output delivery
are not part of this interface.
