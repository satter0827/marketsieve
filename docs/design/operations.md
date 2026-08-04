# Operations

## Supported current operation

MarketSieve currently supports local development, public SDK builds, version reporting, and offline
foundation diagnostics on Python 3.12 through 3.14. Python 3.13 is the primary development version.

```shell
make sync
uv run marketsieve --version
make doctor
make build
```

These operations require no secrets, provider accounts, network data, database, scheduler, or
delivery configuration. The application does not persist operational state.

Project-local caches and generated artifacts are rooted at `.marketsieve`. The `.venv` directory is
the only repository-root development environment. Human, agent, editor, and CI workflows use the
Makefile entry points so their commands do not drift.

## Approved preview operation

The Offline Analysis Preview adds a deterministic demo backed only by repository-licensed synthetic
fixtures. It remains runnable after dependency installation without external accounts or live
services. Generated command output is ephemeral and is not committed as a report or fixture.

Failures identify whether input validation, analysis prerequisites, or an internal contract caused
the operation to stop. They do not expose environment secrets or silently switch data sources.

## Unsupported operation

Live-data acquisition, scheduled execution, persistent state, report delivery, provider fallback,
and LLM-assisted reporting are not supported operations. When later milestones introduce them,
their configuration, recovery, observability, and secret-handling procedures must be added here in
the same change.
