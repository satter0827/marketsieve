# MarketSieve Rakuten Import

`marketsieve-import-rakuten` is an independently installable portfolio adapter for MarketSieve.

The 0.7 contract accepts only a CP932 `assetbalance(all)` export whose portfolio-detail section
explicitly says that no holdings exist. It returns an empty brokerage-neutral portfolio and records
the source digest without retaining the source path or bytes. Non-empty Rakuten exports are rejected
until an anonymized real export establishes their columns and semantics.

```shell
pip install marketsieve-cli marketsieve-import-rakuten
marketsieve portfolio import --broker rakuten --as-of 2026-08-06T12:48:40+09:00 PATH.csv
```
