# Domain

This document defines the approved semantics for the Offline Analysis Preview. Exact Python type
names and signatures are established with their first working implementation and contract tests.

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
- Sorting, range validation, and duplicate detection use the exchange trading date.

## Daily observations

A daily bar contains a trading date, open, high, low, close, volume, adjustment state, and
provenance. Prices use an exact decimal representation at the domain boundary.

- Prices are finite and non-negative; volume is a non-negative integer.
- `low` is no greater than open, high, and close.
- `high` is no less than open, low, and close.
- A series is strictly ordered by trading date and contains no duplicate trading dates.
- The adjustment state is explicit. Raw and adjusted observations are not interchangeable.

## Completeness and provenance

Completeness states whether the returned observations cover the accepted request. A partial range
is never reported as complete. Provenance identifies the source, dataset or fixture identity,
retrieval or generation context, and adjustment meaning needed to reproduce the input.

Data from different providers or adjustment states is not merged implicitly. Missing observations
are not fabricated, forward-filled, or substituted with a different frequency.

## Analysis and evidence

SMA20 is the arithmetic mean of the latest 20 eligible closing observations as of the analysis
date. A state identifies whether the latest close is above, below, or equal to SMA20. A state change
exists only when two consecutive eligible analysis points have different states.

Insufficient history is an explicit non-signal result. A state change is an observed market-data
condition, not a buy, sell, suitability, or risk recommendation.

Evidence identifies the validated inputs, date range, indicator definition, computed value, and
decision rule used for a result. The same inputs and analysis definition produce the same evidence
identity and result.
