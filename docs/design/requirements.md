# Requirements

## Product objective

MarketSieve provides reproducible analysis of Japanese and U.S. equities. It separates reusable
market semantics and deterministic calculations from provider access, operational configuration,
report generation infrastructure, and delivery channels.

## Current foundation

- **FND-01:** The `marketsieve` distribution builds and installs as a typed public SDK.
- **FND-02:** The repository-local application exposes version and offline diagnostic commands.
- **FND-03:** The public SDK remains independent from the application, configuration, logging,
  network clients, databases, delivery providers, and LLM providers.
- **FND-04:** Local and CI gates verify code quality, tests, and public distribution isolation.
- **FND-05:** Normal changes enter `develop`; a human-reviewed `develop -> main` promotion remains
  the release boundary.

## Approved target: Offline Analysis Preview

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

## Exclusions from the approved target

The preview does not include investment recommendations, live data, CSV ingestion, persistence,
scheduling, email or LINE delivery, LLM reporting, portfolio management, automatic provider
discovery, or automatic merging of provider data. These capabilities require later roadmap
decisions and implementation evidence.
