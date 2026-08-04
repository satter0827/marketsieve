# marketsieve-agent

Optional grounded explanation pipeline for MarketSieve. The model may select validated fact IDs
and provide short non-numeric connective text. MarketSieve renders every value, date, instrument,
evidence ID, and disclaimer deterministically.

FakeListLLM is the default implementation. The package does not fetch market data, calculate
indicators, call tools, access files, or perform trading operations.
