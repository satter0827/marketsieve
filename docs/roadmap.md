# Roadmap

The roadmap orders independently testable outcomes. Implemented behavior belongs in the formal
design and release history, not in this file.

## 0.4.0 Personal Close Brief

1. Add minimal portfolio input and a Rakuten importer based on anonymized real fixtures.
2. Add one-command Japanese close, U.S. close, and weekly report workflows.
3. Replace generic JSON-shaped terminal output with conclusion-first Close Brief projections.

## 0.5.0 Official Fundamentals

1. Add SEC submission and XBRL acquisition with publication-time semantics.
2. Add EDINET document and XBRL acquisition with the same normalized financial contract.
3. Preserve corrections, accounting basis, fiscal period, consolidation, currency, and provenance.
4. Add knowledge-as-of financial trends and company-history valuation comparisons.
5. Integrate filing changes into daily and weekly reports without coupling reports to a provider.

## 0.6.0 Strategy Lab

1. Add immutable experiment specifications and replay windows that reuse decision policies.
2. Replay only facts available at each historical as-of instant.
3. Measure coverage, decision activity, churn, holding period, drawdown, and forward return.
4. Persist reproducible experiment runs and comparisons.
5. Compare prompts and models without allowing an LLM to own calculations or decisions.

## 0.7.0 Screening Workbench

1. Add explicit Japanese and U.S. instrument-universe import and acquisition capabilities.
2. Add a typed balanced candidate screen without arbitrary expression evaluation.
3. Enforce configured acquisition and processing budgets without silently changing the universe.
4. Persist deterministic screening reports with stable, explainable ordering.
5. Integrate screening candidates into the weekly report without changing held-instrument decisions.
6. Prepare verified GitHub Release and PyPI Trusted Publishing paths for all public distributions.

## Later outcomes

- Add delivery only when a working channel defines receipts, retries, idempotency, and recipient
  protection.
- Add scheduling only when one-shot commands and persisted reports have proved operationally
  reliable.
- Add news only after licensing, deduplication, reliability, and prompt-injection rules are defined.
