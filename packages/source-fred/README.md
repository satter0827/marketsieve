# MarketSieve FRED source

This distribution fetches one explicitly selected economic series from the official FRED
`series/observations` endpoint. It records the requested historical knowledge date and the
provider's real-time revision interval for every value. Missing `.` observations remain explicit.

The adapter reads a 32-character key only from `FRED_API_KEY`. It performs no implicit series
selection, transformation, retry, fallback, or persistence. Tests inject an offline transport.
