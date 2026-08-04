# Requirements

## Product objective

MarketSieve provides reproducible analysis of Japanese and U.S. equities. It separates reusable
market semantics and deterministic calculations from provider access, operational configuration,
report generation infrastructure, and delivery channels.

## Current foundation

- **FND-01:** The `marketsieve` distribution builds and installs as a typed public SDK.
- **FND-02:** The public CLI distribution exposes version and offline diagnostic commands.
- **FND-03:** The public SDK remains independent from the application, configuration, logging,
  network clients, databases, delivery providers, and LLM providers.
- **FND-04:** Local and CI gates verify code quality, tests, and public distribution isolation.
- **FND-05:** Normal changes enter `develop`; a human-reviewed `develop -> main` promotion remains
  the release boundary.

## Current Offline Analysis Preview

- **OAP-01:** The system represents exchange-qualified Japanese and U.S. equity instruments and
  validated daily OHLCV observations without ambiguous symbols or times.
- **OAP-02:** Repository-licensed synthetic fixtures provide deterministic Japanese and U.S. daily
  series without network access, credentials, or copied live prices.
- **OAP-03:** The first analysis calculates SMA20 and reports only an observable close-versus-SMA20
  state change.
- **OAP-04:** Repeating the same analysis with the same inputs produces the same result and evidence.
- **OAP-05:** Results identify the instrument, market, analysis date, indicator value, state change,
  input date range, and evidence identity.
- **OAP-06:** Insufficient history, invalid observations, unsupported requests, and incomplete data
  are explicit outcomes; the system does not silently weaken a request.
- **OAP-07:** A repository-local offline command demonstrates the complete path from synthetic data
  through validated analysis to an evidence-backed result.

## Current 0.1.0 historical report

- **HRC-01:** Historical replay reloads the exact source request at each explicit as-of instant so
  later observations or revisions cannot determine an earlier result.
- **HRC-02:** A channel-neutral report contains the latest SMA20 state, observed state changes,
  provenance, and evidence references without expressing an investment recommendation.
- **HRC-03:** The repository-local CLI presents the same report as terminal-rich, plain-text, or
  versioned JSON output.
- **HRC-04:** AI clients can discover commands, options, schemas, exit codes, and side effects from
  a deterministic capabilities command.

## Exclusions from 0.1.0

The 0.1.0 release does not include investment recommendations, live data, CSV ingestion,
persistence, scheduling, email or LINE delivery, LLM reporting, portfolio management, automatic provider
discovery, or automatic merging of provider data. These capabilities require later roadmap
decisions and implementation evidence.

## Approved 0.2 Data Workbench target

- **DWB-01:** A separately installable CLI reads immutable local snapshots and does not perform
  network access during inspection, analysis, comparison, or report rendering.
- **DWB-02:** CSV, J-Quants, and Alpha Vantage integrations remain separate distributions and are
  selected explicitly by a named source profile without automatic fallback or provider merging.
- **DWB-03:** Acquisition distinguishes the market observation date, provider publication time,
  local retrieval time, and the basis used to decide when a fact became available.
- **DWB-04:** A content-addressed snapshot retains normalized facts, provenance, completeness, and
  permitted raw-response evidence without retaining credentials or recipient or portfolio data.
- **DWB-05:** Inspection presents independent price, technical, financial, valuation, risk, event,
  and data-quality sections. One unavailable section does not invalidate the others.
- **DWB-06:** SMA, EMA, RSI, MACD, ATR, period return, and maximum drawdown use versioned,
  deterministic definitions and do not depend on process-wide decimal settings.
- **DWB-07:** Financial facts retain accounting period, standard, consolidation, currency, scale,
  publication, revision, and provenance semantics before a derived ratio is calculated.
- **DWB-08:** Comparison identifies incompatible periods, accounting bases, and currencies rather
  than ranking or converting incomparable values.
- **DWB-09:** Japanese and English human output project the same versioned English-keyed machine
  contracts. Partial results expose completeness and missing reasons.
- **DWB-10:** The CLI, extension contract, and provider integrations build as isolated artifacts and
  are distributed together through a checksummed GitHub Release wheelhouse.

## Approved 0.3 Report Agent target

- **RAG-01:** The report agent receives only a validated fact catalog derived from the same sections
  used by deterministic CLI projections.
- **RAG-02:** The model selects fact identifiers, section order, and non-numeric connective text. A
  deterministic renderer owns numbers, dates, instruments, evidence, and disclaimers.
- **RAG-03:** FakeListLLM is the default test model. LM Studio, OpenAI, Anthropic, and Google remain
  explicit provider choices with no local-to-cloud or cloud-to-cloud fallback.
- **RAG-04:** A cloud request requires an explicit per-invocation opt-in and offers a dry-run view of
  the outgoing payload without credentials.
- **RAG-05:** Invalid, ungrounded, unsafe, or unavailable model output is discarded and replaced by
  a deterministic template derived from the same facts.
- **RAG-06:** The agent cannot fetch sources, recalculate facts, call tools, access files, place
  orders, rank investments, or produce buy, hold, or sell recommendations.

## Exclusions from 0.2 and 0.3

The approved targets exclude news, screening, portfolio management, scheduling, delivery channels,
databases, foreign-exchange conversion, automatic provider discovery and execution, automatic
fallback, automatic provider merging, investment scores, recommendations, and trading operations.
