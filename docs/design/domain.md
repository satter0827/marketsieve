# Domain

This document defines the current market-data, analysis, replay, and report semantics. The public
types live below `marketsieve.domain`, `marketsieve.data`, `marketsieve.analysis`,
`marketsieve.reporting`, and `marketsieve.synthetic`.

## Instrument identity

An equity instrument is identified by a provider-independent symbol together with an ISO 10383
Market Identifier Code. A symbol without a market is ambiguous and is rejected at a public
boundary. Currency and exchange timezone are explicit properties; they are not inferred from the
symbol text.

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

SMA20 is the exact arithmetic mean of the latest 20 eligible closing observations as of the
analysis date. Its value and comparison do not depend on the process-wide decimal context. A state
identifies whether the latest close is above, below, or equal to SMA20. A reported state change
exists only when two consecutive valid replay points have different states; a point does not report
changes inferred from observations that were not evaluated by the replay.

Insufficient history is an explicit non-signal result. A state change is an observed market-data
condition, not a buy, sell, suitability, or risk recommendation.

Evidence identifies the validated inputs, date range, indicator definition, computed value, and
decision rule used for a result. The same inputs and analysis definition produce the same evidence
identity and result.

## Historical replay

A replay evaluates one exact daily-bar request at a non-empty sequence of unique timezone-aware
as-of instants that is strictly increasing after UTC normalization. The source is loaded
independently at every instant. A replay does
not derive earlier results by truncating the final dataset because that dataset may contain values
revised after an earlier evaluation instant.

Each replay point retains its as-of instant, analysis result, provenance, and evidence identity.
Insufficient history is a successful replay point. Identical requests, evaluation instants, source
responses, and analysis definitions produce the same replay identity.

## Historical report

The SMA20 replay report contains the latest evaluated result and only changes observed between
consecutive valid replay points. Insufficient-history points and repeated snapshots do not create
transitions. It references the replay, provenance, and analysis evidence without changing
calculated facts. The report is channel-neutral and contains no recommendation, forecast, or
suitability decision. Its identity is derived from normalized report content rather than rendered
text.

## Approved 0.2 availability model

The target model distinguishes four related values:

- `observation_date` identifies the market or accounting period being described;
- `published_at` identifies when the source or issuer made the fact available, when known;
- `retrieved_at` identifies when MarketSieve acquired the response;
- `availability_basis` is `published` or `retrieval` and identifies which instant bounds as-of use.

A fact without a verified publication instant uses retrieval availability and cannot support a claim
about knowledge before it was retrieved. Historical coverage is not evidence of historical
availability. Restated facts retain their revision identity rather than replacing earlier snapshot
evidence.

## Approved 0.2 financial facts

A normalized financial fact retains its provider name, normalized concept, accounting standard,
annual, quarterly, or trailing period, fiscal boundaries, publication instant, consolidation basis,
reported or restated status, currency, scale, and provenance. Derived growth, margin, return,
leverage, and valuation values are calculated only from compatible inputs. Provider-reported and
MarketSieve-derived ratios remain distinguishable.

## Approved 0.2 indicator semantics

The target indicator catalog contains SMA, EMA, RSI, MACD, ATR, period return, and maximum drawdown.
Every result records its parameters, definition version, observation count, status, numeric policy,
and evidence identity. The numeric policy uses a local decimal context with 34 digits and
round-half-even. SMA aggregates exact fractions before one decimal conversion; recursive indicators
perform each recurrence inside the fixed local context. Definition versions state the input field,
warm-up, seed, recurrence, intermediate precision, and output normalization rules.

Insufficient history is a non-signal result. NaN, infinity, invalid parameters, zero denominators,
and incompatible currencies or accounting periods are never silently coerced into a value.

## Approved 0.2 section semantics

Instrument, price, technical, financial, valuation, risk, event, and data-quality sections are
independent evidence-bearing results. A section may be complete, partial, unavailable, or invalid.
Missing facts include machine-readable reasons. Comparison uses a common knowledge-as-of instant and
does not rank incompatible periods, accounting bases, consolidation bases, or absolute values in
different currencies.
