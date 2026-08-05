# marketsieve-agent

Optional grounded explanation pipeline for immutable MarketSieve decision reports. The model may
select validated fact IDs and provide short non-numeric connective text. MarketSieve renders every
decision value, date, instrument, and evidence ID deterministically.

The caller must explicitly supply one model provider. Test doubles live only in tests. The package
does not fetch market data, read portfolio files, calculate decisions, call tools, access files, or
perform trading operations. Quantities and acquisition prices are not included in the fact catalog.
