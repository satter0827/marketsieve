# Domain

An instrument is identified by `MIC:SYMBOL` and has one trading currency and exchange timezone. An
index membership is classification metadata and may overlap other memberships.

A daily bar contains exchange-local trading date, OHLC, volume, adjustment basis, availability time,
and provenance. A Market Snapshot is a cross-sectional observation created from one explicit scope,
evidence selection, date window, effective settings document, universe asset version, and provider
response. Each defined field is either present or paired with one stable missing reason.

An aggregate is a neutral summary for all securities or one market, index, sector, or industry. It
does not rank securities. A Security Research Pack is retrieval evidence for one Snapshot security,
including selected time series, facts, events, benchmarks, definitions, and quality evidence.

An input changes the requested analytical result and belongs to a single invocation. A setting
controls bounded execution or quality behavior and may persist. This distinction prevents hidden
scope and makes generated evidence reproducible.
