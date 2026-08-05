# External universe plugin example

This package is intentionally outside the MarketSieve workspace and public-package catalog. It
shows the complete boundary needed by an independently developed plugin: compatible SDK and
extension-API requirements, one capability entry point, typed normalized output, and the public
conformance check.

The input is a UTF-8 CSV with this header:

```text
mic,symbol,currency,timezone
```

Build the project as its own wheel and install it beside MarketSieve. `marketsieve source list`
then discovers `example-universe` without importing the plugin. This example is documentation and
distribution-test input; it is not one of the packages published by this repository.
