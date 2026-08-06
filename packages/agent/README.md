# marketsieve-agent

Optional grounded explanation pipelines for immutable MarketSieve decision reports and experiment
runs. The model selects validated fact IDs. MarketSieve renders every decision, metric, date,
instrument, and evidence ID deterministically.

The caller must explicitly supply one model provider. Test doubles live only in tests. The package
does not fetch market data, read portfolio files, calculate decisions, call tools, access files, or
perform trading operations. Quantities and acquisition prices are not included in the fact catalog.
