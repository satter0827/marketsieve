# Domain

This document defines current market-data, indicator, financial-fact, and evidence semantics. The
public types live below `marketsieve.domain`, `marketsieve.data`, `marketsieve.analysis`, and
`marketsieve.synthetic`.

## Instrument identity

An equity instrument is identified by a provider-independent symbol together with an ISO 10383
Market Identifier Code. A symbol without a market is ambiguous and is rejected at a public
boundary. Symbols start with an uppercase letter or digit and may contain uppercase letters,
digits, dots, and hyphens so U.S. class-share identifiers remain representable. Currency and
exchange timezone are explicit properties; they are not inferred from symbol text.

Provider symbols are adapter data. Mapping them to an exchange-qualified instrument is explicit and
must not alter the domain identity.

## Market time

A trading date is the exchange-local date to which a daily observation belongs. It is distinct from
an ingestion timestamp and from an analysis `as-of` instant.

- Observation and ingestion instants are timezone-aware.
- Naive datetimes are invalid at public boundaries.
- An analysis may use only observations available at or before its `as-of` instant.
- Instant ordering, equality, duplicate detection, and availability compare normalized UTC values;
  local wall-clock equality does not collapse the two sides of a daylight-saving fold.
- Sorting, range validation, and duplicate detection use the exchange trading date.

## Daily observations

A daily bar contains a trading date, open, high, low, close, volume, adjustment state, and
provenance. Prices use an exact decimal representation at the domain boundary.

- Prices are finite and positive; volume is a non-negative integer.
- `low` is no greater than open, high, and close.
- `high` is no less than open, low, and close.
- A series is strictly ordered by trading date and contains no duplicate trading dates.
- The adjustment state is explicit. Raw and adjusted observations are not interchangeable.

## Completeness and provenance

Capability rejects an instrument, range, or adjustment that a source cannot satisfy. Observations
inside an accepted request but unavailable at the `as-of` instant are excluded and counted
explicitly. Provenance identifies the source, immutable dataset identity, and version; the request
and each bar retain adjustment and availability meaning needed to reproduce the input.

Data from different providers or adjustment states is not merged implicitly. Missing observations
are not fabricated, forward-filled, or substituted with a different frequency.

## Analysis and evidence

SMA, EMA, RSI, MACD, ATR, period return, and maximum drawdown have versioned definitions and fixed
local numeric policy. Insufficient history is an explicit non-signal result. Indicators describe
observed market data and are not buy, sell, suitability, or risk recommendations.

Evidence identifies the validated inputs, date range, indicator definition, computed value, and
decision rule used for a result. The same inputs and analysis definition produce the same evidence
identity and result.

## Availability model

CSV acquisition distinguishes four related values:

- `observation_date` identifies the market or accounting period being described;
- `published_at` identifies when the source or issuer made the fact available, when known;
- `retrieved_at` identifies when MarketSieve acquired the response;
- `availability_basis` is `published` or `retrieval` and identifies which instant bounds as-of use.

A fact without a verified publication instant uses retrieval availability and cannot support a claim
about knowledge before it was retrieved. Historical coverage is not evidence of historical
availability. Restated facts retain their revision identity rather than replacing earlier snapshot
evidence.

Normalized daily bars retain the trading date and selected availability instant. Financial facts
retain the provider publication instant and fiscal period. Events with a provider publication time
use it; an earnings schedule without one uses retrieval availability and cannot enter an earlier
knowledge-as-of view. Snapshot manifests separately retain retrieval time.

## Financial facts

A filing document has a provider-stable filing ID, issuer ID, document type, aware publication
instant, optional amendment target, and the fiscal and accounting dimensions the provider states.
An amendment is a separate filing and never overwrites its original. Filing collections use stable
publication order and reject duplicate identities or documents published after retrieval.

A normalized financial fact retains its provider name, normalized concept, accounting standard,
annual, single-quarter, cumulative interim, or trailing period, the provider's period label, known
fiscal boundaries, publication instant, consolidation basis,
reported or restated status, currency, scale, and provenance. Derived growth, margin, return,
leverage, and valuation values are calculated only from compatible inputs. Provider-reported and
MarketSieve-derived ratios remain distinguishable.

A fact may reference one filing included in the same acquisition. Its publication instant must
match that filing. Knowledge-time selection includes only filings whose publication instant and
facts whose availability instant are no later than the requested aware instant. The normalized
financial snapshot stores both the filing collection and each fact-to-filing link.

When a provider omits a fiscal-period start, consolidation basis, revision state, accounting
standard, or publication instant, the normalized fact keeps that dimension unknown and reports a
missing reason. MarketSieve does not manufacture a period boundary or treat an unspecified basis as
compatible.

The implemented J-Quants summary mapping preserves `1Q` as a single quarter, `2Q` and `3Q` as
cumulative interim periods, and `FY` as annual. It covers revenue, operating income, net income, EPS,
operating cash flow, assets, and equity for consolidated and non-consolidated disclosures. A field
that the summary endpoint does not provide, including accounting standard and interest-bearing
debt, remains absent with an explicit reason. MarketSieve does not infer those values or construct
free cash flow inside a source adapter.

Financial completeness is the fraction of base and compatible derived target concepts present.
Event completeness is endpoint coverage across dividend, earnings, and split facts, not the number
of events that happened in a period. Missing accounting standard or other required dimensions keep
the section partial even when every mapped concept is present. Each normalized fact retains the
source, dataset, and source-version provenance of its immutable acquisition.

The SDK financial-history calculation accepts normalized observations with explicit availability
and evidence identities. It first excludes observations unavailable at the requested knowledge
instant. It then selects annual periods with known boundaries, accounting standard, consolidation,
revision state, and currency. A later known observation for the same concept and period supersedes
an earlier value for calculation without deleting either observation from acquisition evidence.
Conflicting values with the same availability instant are invalid.

The current and immediately preceding periods must use the same accounting standard,
consolidation basis, and currency. The preceding period must end before the current period starts.
The calculation derives free cash flow, revenue and EPS growth, operating and net margins, ROE,
ROA, equity ratio, and debt-to-equity only when their compatible inputs exist. Missing results use
stable machine-readable reasons. Period values, selected evidence IDs, metric definitions, and the
knowledge instant form a deterministic financial-trend identity. The CLI projects this typed result
into report sections; it does not own the calculations.

## Economic series

An economic observation contains an observation date, a finite decimal value, and the inclusive
real-time start and end dates for which that revision is valid. An economic series selects one
explicit provider series identifier and one knowledge date. Every included revision
must be valid on that knowledge date.

Observations are unique and ordered by observation date. A provider's missing-value marker is
stored as an explicit missing observation date and is never converted to zero or carried forward.
Retrieval time and response identity belong to the acquisition result rather than the economic
value. The same observation date cannot be both valued and missing.

## Indicator semantics

The implemented indicator catalog contains SMA, EMA, RSI, MACD, ATR, period return, and maximum drawdown.
Every result records its parameters, definition version, observation count, status, numeric policy,
and evidence identity. The numeric policy uses a local decimal context with 34 digits and
round-half-even. SMA aggregates exact fractions before one decimal conversion; recursive indicators
perform each recurrence inside the fixed local context. Definition versions state the input field,
warm-up, seed, recurrence, intermediate precision, and output normalization rules.

Insufficient history is a non-signal result. NaN, infinity, invalid parameters, zero denominators,
and incompatible currencies or accounting periods are never silently coerced into a value.

The v1 definitions use close as the input for SMA, EMA, RSI, MACD, period return, and drawdown. EMA
uses an SMA seed and alpha `2 / (period + 1)`. RSI and ATR use Wilder recurrence after an SMA seed;
a completely flat RSI seed is 50. ATR true range includes the previous close after the first bar.
MACD uses independently seeded fast and slow EMAs, then an SMA-seeded EMA for its signal. Period
return is `latest / close[period ago] - 1`. Maximum drawdown is the minimum peak-relative return in
the selected trailing window and is zero or negative.

Outputs are canonical non-exponent decimal strings with redundant trailing zeros removed. Invalid
or extra parameters are errors. Insufficient history returns no numeric values but retains the
input count, definition, policy, as-of instant, and evidence. Reference vectors in
`tests/unit/test_indicators.py` are the executable authority for all seven definitions.

## Section semantics

Instrument, price, technical, financial, valuation, risk, event, and data-quality sections are
independent evidence-bearing results. A section may be complete, partial, unavailable, or invalid.
Missing facts include machine-readable reasons. Comparison uses a common knowledge-as-of instant and
does not rank incompatible periods, accounting bases, consolidation bases, or absolute values in
different currencies.

## Portfolio and decision semantics

A portfolio snapshot is an immutable, brokerage-neutral observation of holdings and watch items at
one aware instant. A holding identifies an instrument, quantity, average acquisition price,
currency, and account type. Optional personal context contains only explicit policy inputs such as
a position-weight limit. It does not contain credentials, account numbers, orders, or transactions.

A market session is `jp_close`, `us_close`, or `weekly`. It identifies the report scope and target
as-of instant; it does not infer that an exchange was open. Acquisition evidence remains the
authority for observation availability.

A decision is a policy result, not an order. Held instruments use `keep`, `watch`, `reduce_review`,
`sell_review`, or `indeterminate`. Unheld instruments use `buy_candidate`, `wait_for_pullback`,
`wait_for_earnings`, `pass`, or `indeterminate`. Human projections translate these stable values.

Each decision records confidence, supporting evidence, opposing evidence, invalidation conditions,
the next review action, policy identity, policy settings, input evidence, financial disclosure
context, and company-relative valuation context. Missing essential price history produces an
indeterminate decision. Missing non-essential facts lower confidence and remain visible.

The balanced medium-term policy uses SMA 20 and 60, RSI 14, MACD 12/26/9, ATR 14, 20-day return,
and 252-day maximum drawdown. Its defaults are RSI 70/30, ATR-to-close warning at 4 percent,
drawdown warning at -20 percent, earnings wait at seven calendar days, and position concentration
warning above 20 percent. Policy settings are explicit values included in evidence identity.

SMA 20 and 60, RSI, MACD, ATR, and 20-day return are essential price inputs. Missing history for
one of them produces `indeterminate`. The 252-day drawdown and financial inputs are optional;
their absence lowers confidence and remains explicit. Confidence is high when drawdown and all
three financial inputs are present, medium when drawdown or at least two financial inputs are
present, and low otherwise.

Held decisions apply rules in this order: financial deterioration with a bearish trend produces
`sell_review`; financial deterioration, concentration, or a bearish high-volatility combination
produces `reduce_review`; a bearish trend, high volatility, deep drawdown, or overbought RSI
produces `watch`; otherwise the result is `keep`. Unheld decisions first wait for an earnings date
within seven local calendar days. Financial deterioration, a bearish trend, high volatility, or a
deep drawdown then produces `pass`. A bullish trend that is not overbought produces
`buy_candidate`; an overbought or temporarily weakened long trend, or an oversold neutral trend,
produces `wait_for_pullback`; all other cases produce `pass`.

Financial deterioration means at least two negative values among revenue growth, EPS growth, and
free cash flow. Valuation values are retained as display evidence and do not reverse a 1.0.0 policy
decision. Company-relative valuation uses only explicitly acquired observations for the same
exchange-qualified instrument. It shows the current value and observation count, and adds minimum,
median, and maximum when at least two observations exist. It does not compare industries or create
an aggregate score. Filing context identifies the latest known filing, its publication time, and
explicit amendment linkage. When both linked filings contain the same concept, changed concepts
are listed without interpreting their materiality. The policy never converts an action into an
order.

A decision report is an immutable composition of one market session, one portfolio snapshot, the
selected policy, per-instrument decisions, input diagnostics, and an optional previous-report
link. Its identity is a digest of canonical semantic content. Locale-specific headings and terminal
styling are projections and do not affect identity.

## Experiment semantics

An experiment specification fixes the decision policy name, version, settings, replay window, and
the content identifier for every exchange-qualified instrument dataset. A replay calls the same
decision policy used by routine analysis and supplies only bars available at each historical
instant. A specification and its deterministic decisions and metrics form the content-addressed
run identity.

The implemented metrics are data coverage, decision count, decision changes, average consecutive
active-signal period, maximum drawdown inside the replay window, and next-observation return.
Forward return describes subsequent data; it is not a portfolio profit. An experiment is labeled a
profit simulation only when commission, tax, and foreign-exchange cost rates are all fixed. The
current engine does not apply those costs and therefore exposes no net-profit metric.
