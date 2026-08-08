# Domain

An instrument is identified by `MIC:SYMBOL` and has one trading currency and exchange timezone. An
index membership is classification metadata and may overlap other memberships.

A daily bar contains exchange-local trading date, OHLC, volume, adjustment basis, availability time,
and provenance. A Market Snapshot is a cross-sectional observation created from one explicit scope,
evidence selection, date window, effective settings document, universe asset version, and provider
response. Each defined field is either present or paired with one stable missing reason.

An aggregate is a neutral summary for all securities or one market, index, sector, industry, or
market-sector intersection. It
does not rank securities. A Security Research Pack is retrieval evidence for one Snapshot security,
including selected time series, facts, events, benchmarks, definitions, and quality evidence.

An input changes the requested analytical result and belongs to a single invocation. A setting
controls bounded execution or quality behavior and may persist. This distinction prevents hidden
scope and makes generated evidence reproducible.

Retrieval time, price trading date, financial fiscal-period end, statement period, and provider
availability basis are distinct facts. A retrieval timestamp never backdates a financial fact.
Provider percentage-point fields are normalized to stored ratios at acquisition. Applicability is
part of each field definition; `not_applicable` observations do not enter aggregate denominators.

An Explorer Projection is a deterministic view contract over authoritative JSON and JSONL. It
contains source references, fields, units, periods, applicability, and display definitions, but
does not duplicate authoritative observations. Rendering derives drawing marks and table fallbacks
from saved evidence without acquisition or persistence. It does not add conclusions, scores,
recommendations, or model prompts.

A Capture run records one market close session and explicit evidence domains. Historical price
reconstruction is a separate mode that contains only price and benchmark evidence and may not
reuse present-day company or financial facts.
