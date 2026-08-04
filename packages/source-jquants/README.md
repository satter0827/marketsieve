# MarketSieve J-Quants source

This distribution implements explicit J-Quants API V2 acquisition for Tokyo Stock Exchange daily
bars and instrument profile facts. It reads the API key only from `JQUANTS_API_KEY`, never stores a
raw response, and performs no automatic provider fallback or requested-range shortening.

Select it through a `marketsieve.toml` source profile and run `marketsieve source fetch` explicitly.
