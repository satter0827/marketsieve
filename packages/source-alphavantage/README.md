# MarketSieve Alpha Vantage source

This distribution implements explicit Alpha Vantage acquisition for U.S. BATS, XNAS, and XNYS
equities.
It supports raw and premium adjusted daily prices, company overview facts, financial statements,
earnings reports, dividends, and splits. It reads `ALPHAVANTAGE_API_KEY` only for the selected fetch
command, stores no raw response, and never retries, shortens, substitutes, or falls back from an
unsupported exact request.

Daily settings declare `plan = "free"` or `plan = "premium"` and `outputsize = "compact"` or
`outputsize = "full"`. Adjusted prices and full history require an explicitly configured premium
plan. Event settings select any combination of `earnings`, `dividend`, and `split`; the default is
`earnings`.
