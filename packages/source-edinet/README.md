# MarketSieve EDINET Source

Explicit acquisition of EDINET filing lists and XBRL-derived TSV ZIP files for one EDINET code.
Set `EDINET_API_KEY` only in the invoking environment and configure the issuer's EDINET code
explicitly. The key is sent only in the official query parameter and is never retained.

The adapter retains document IDs, Japanese submission times, parent-document amendment links,
fiscal periods, accounting standards, consolidation scope, currency, and fact-to-filing links. It
maps a small named set of standard taxonomy concepts. It does not guess an EDINET code from a
symbol, interpret issuer-specific taxonomy extensions, retain downloaded ZIP files, or make an
investment decision.
