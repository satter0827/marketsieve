# MarketSieve J-Quants source

This distribution implements explicit J-Quants API V2 acquisition for Tokyo Stock Exchange daily
bars, instrument profiles, financial summaries, dividends, and earnings schedules. It reads the API
key only from `JQUANTS_API_KEY`, never stores a raw response, and performs no automatic provider
fallback or requested-range shortening.

Select each data kind through a `marketsieve.toml` source profile and run `marketsieve source fetch`
explicitly. Event settings default to the Free-plan earnings endpoint. Add `dividend` to
`event_types` only when the configured plan permits the Premium endpoint. Split events remain
explicitly missing because the selected J-Quants V2 contracts do not provide a split event fact.
