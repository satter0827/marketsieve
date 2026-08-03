# Architecture

## Purpose

MarketSieve separates reusable market semantics from one maintainer's operational environment. The
public SDK remains installable without provider credentials, delivery SDKs, persistence drivers, or
the repository-local CLI.

## Components

The `marketsieve` distribution is the only public artifact. It will own market domain values,
deterministic analysis, experiment definitions, channel-neutral reports, and public integration
ports as those capabilities are implemented.

The `marketsieve_app` package is a repository-local application. It owns orchestration,
configuration, structured logging, persistence, retries, schedules, external data sources, report
agents, and delivery adapters. Its CLI is one interface into the application rather than the
application itself.

## Dependency rules

```text
CLI and scheduler
        |
        v
Application services <--- Adapters
        |
        v
marketsieve SDK
```

- The SDK uses no application, CLI, environment, logging, network, database, SMTP, LINE, or LLM
  dependencies.
- Application services depend on public SDK values and ports.
- Adapters implement application coordination or public ports; they do not define market rules.
- Interfaces translate external input and output; they do not implement analysis or delivery
  policy.
- Empty future-facing modules and placeholder protocols are not added. A boundary becomes public
  with its first working implementation and tests.

## Delivery boundary

Channel-neutral reports will be produced by the SDK. A repository-local delivery coordinator will
choose recipients, derive idempotency keys, suppress duplicates, classify failures, and persist
delivery receipts. Console, SMTP email, and LINE Messaging API integrations will remain concrete
adapters. Credentials and recipient identifiers never enter SDK values.

## Packaging

`uv build --package marketsieve` is the only supported public build. Release automation will use an
explicit allowlist so `marketsieve_app`, tests, caches, and local configuration cannot enter public
artifacts. The repository-local application is installed by the uv workspace only.
