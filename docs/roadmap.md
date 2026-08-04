# Roadmap

The roadmap orders planned outcomes by dependency and evidence. It is not a description of current
behavior; current and approved near-term constraints live in the [formal design](design/README.md).

## Foundation and 0.1.0 — complete

- Publish the typed, I/O-independent `marketsieve` SDK.
- Validate exchange-qualified daily bars with deterministic Japanese and U.S. synthetic data.
- Prove deterministic evidence with the initial SMA20 preview.
- Establish reproducible local, review, develop, and release gates.

## 0.2.0 Data Workbench — approved

Each milestone must remain usable without later milestones.

1. ~~Establish the target design, repository secret controls, and redacted evidence policy.~~
2. ~~Publish an independently installable CLI and build a checksummed multi-package wheelhouse.~~
3. ~~Prove the extension contract with CSV import, immutable daily-bar snapshots, and price inspection.~~
4. ~~Replace SMA20-specific analysis with SMA, EMA, RSI, MACD, ATR, return, and drawdown results.~~
5. ~~Add J-Quants API V2 price and instrument profile acquisition with explicit profile selection.~~
6. ~~Add J-Quants financial and event facts with explicit availability.~~
   - ~~Normalize financial summaries, explicitly selected dividends, and earnings schedules.~~
   - ~~Keep J-Quants split events missing rather than relabeling a price adjustment factor as a
     confirmed split.~~
7. ~~Add Alpha Vantage capabilities without weakening raw, adjusted, range, or plan requests.~~
8. ~~Complete financial, valuation, risk, comparison, and deterministic report projections.~~
9. ~~Verify the same GitHub Release wheelhouse on every supported Python version before a human
   `develop -> main` promotion.~~

## 0.3.0 Grounded Report Agent — approved

1. ~~Build a fact-selection pipeline with FakeListLLM and deterministic template fallback.~~
2. ~~Add loopback-only-by-default LM Studio through its OpenAI-compatible endpoint.~~
3. ~~Add explicit, separately tested OpenAI, Anthropic, and Google integrations.~~
4. ~~Reject ungrounded, numeric, unsafe, or recommendation-like model content before rendering.~~
5. ~~Require per-invocation cloud consent and expose credential-free payload dry runs.~~
6. Verify the multi-package artifacts before a human `develop -> main` promotion.

## Later outcomes

- Add screening only after an instrument-universe contract and bounded expression language exist.
- Add news only after licensing, deduplication, reliability, and prompt-injection rules are approved.
- Add persistent operational state only when scheduling or delivery provides a working use case.
- Add SMTP and LINE delivery only after receipts, retries, idempotency, and recipient protection.

Automatic provider fallback, provider merging, foreign-exchange conversion, investment scoring,
recommendations, portfolio management, and trading operations are not planned outcomes.
