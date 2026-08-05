# MarketSieve CSV Source

Strict offline importer for manifest-backed daily-bar CSV bundles. Instrument,
market, timezone, currency, adjustment, and availability are always explicit.

## Bundle format

A bundle is a directory containing `manifest.json` and the named CSV file. No
identity is inferred from the directory or filename.

```json
{
  "schema": "marketsieve-csv-daily-bars/v1",
  "source_profile": "offline-jp",
  "source": "csv",
  "source_version": "dataset-2026-08-01",
  "retrieved_at": "2026-08-01T12:00:00+00:00",
  "instrument": {
    "symbol": "7203",
    "mic": "XTKS",
    "currency": "JPY",
    "timezone": "Asia/Tokyo"
  },
  "dataset": {
    "name": "daily-bars",
    "file": "daily-bars.csv",
    "adjustment": "raw",
    "availability_basis": "published"
  }
}
```

The CSV columns are `trading_date`, `open`, `high`, `low`, `close`, `volume`,
and `published_at`. `published_at` is required when `availability_basis` is
`published`. With `retrieval`, every row becomes available at `retrieved_at`.
Timestamps must carry a UTC offset.

```shell
marketsieve source import ./bundle --plugin csv --output json
```
