# MarketSieve Extension API

Typed contracts implemented by separately installed MarketSieve data sources. Contracts remain
small and data-kind-specific. Current capabilities cover daily bars, filing-linked financial
facts, corporate events, and economic series without owning snapshot storage or source selection.
Financial acquisitions can retain provider filing identity, publication time, amendment linkage,
fiscal period, accounting standard, consolidation basis, and currency. Knowledge-time helpers
exclude filings and facts that were not yet public or available.

The equity-batch capability preserves every requested security, adjusted price observations,
profile and financial values, and normalized partial failures for broad matrix acquisition.

External packages should depend on `marketsieve-extension-api>=0.9,<0.10` and the matching SDK minor
series. The public `verify_instrument_universe_importer` function executes the universe-import
contract against a caller-supplied fixture. The repository's
`examples/instrument-universe-plugin` project shows an independently buildable entry point.
