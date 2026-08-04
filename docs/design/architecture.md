# Architecture

## Purpose

MarketSieve separates reusable market semantics from one maintainer's operational environment. The
public SDK remains usable without provider credentials, configuration sources, logging setup,
network clients, databases, delivery providers, or LLM providers.

## Current components

The `marketsieve` distribution is the only public artifact currently built by this repository. It
contains package metadata and the typed-package marker.

The `marketsieve_app` package is repository-local. It owns the command-line interface and offline
diagnostics and depends on the public SDK. It is not included in public SDK artifacts.

```text
Interface
    |
    v
Application service <--- Adapter
    |
    v
marketsieve SDK
```

- The SDK contains domain semantics, deterministic analysis, channel-neutral results, and only
  those public ports that have a working implementation and tests.
- Application services own use-case orchestration and source-selection policy.
- Adapters own provider, file, persistence, delivery, and other I/O details.
- Interfaces translate external input and output and do not implement market rules.
- Dependencies point inward; the SDK never imports application or infrastructure packages.

## Executable module ownership

The repository-local application uses one composition root. Command interfaces depend on
`marketsieve_app.bootstrap`, the bootstrap module constructs application services, and application
services depend on the public SDK. Interfaces do not import application implementations directly,
and application services do not import bootstrap or interface modules.

Import Linter is the executable authority for layer direction and cycles between these components.
AST structure tests separately protect the SDK from I/O dependencies and protect the public
distribution boundary. New layers or public ports are added only with a working use case and tests;
empty adapter, repository, or base-class packages are prohibited.

The core returns typed results and evidence and does not depend on logging, clocks, handlers,
files, or environment variables. Application services accept a standard-library `Logger` from the
composition root and emit records only at an application boundary. The bootstrap owns logging
configuration and output destinations; command interfaces keep results on stdout and logs on
stderr.

## Approved Offline Analysis Preview

The preview adds a vertical path in dependency order:

```text
Offline demo
    -> application orchestration
    -> synthetic daily-bar source
    -> validated market observations
    -> deterministic SMA20 state-change analysis
    -> evidence-backed result
```

The daily-data boundary is a small, data-kind-specific structural protocol. Its capability model
describes whether a request is supported before retrieval. The protocol and capability model become
public only in the same change as the synthetic implementation and contract tests.

A single source abstraction covering daily bars, intraday bars, quotes, fundamentals, corporate
actions, and instrument search is prohibited. Each future data kind earns a separate boundary from
a working use case.

## Source extension policy

Synthetic data is dependency-free and belongs with the SDK testing and demonstration support.
Sources that perform file or network I/O are separate adapters and, when published, separate
distributions. CSV, J-Quants, and Alpha Vantage are roadmap candidates rather than current
components.

Source registration, priority, fallback, authentication, retries, rate-limit handling, caching,
and provider-symbol mapping belong to the application or adapter packages. A source must not:

- shorten a requested range and report complete success;
- substitute raw data for an adjusted request or change frequency;
- guess a market from a symbol;
- merge providers or conflicting values without an explicit application use case;
- hide authentication, authorization, invalid-response, or data-conflict failures through fallback.

## Packaging boundary

`uv build --package marketsieve` remains the supported public build. An explicit build allowlist
prevents `marketsieve_app`, tests, local configuration, caches, notes, and generated reports from
entering public artifacts. A future adapter distribution has its own dependencies, tests, and
release evidence and does not expand the core SDK dependency set.
