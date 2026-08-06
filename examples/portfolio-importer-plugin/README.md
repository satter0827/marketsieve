# External portfolio importer example

This package is intentionally outside the MarketSieve workspace and public-package catalog. It
shows the complete boundary needed by an independently developed broker adapter: compatible SDK
and extension-API requirements, one portfolio-importer entry point, normalized output, source
identity, and the public conformance contract.

The example accepts a UTF-8 CSV containing only the exact header `status` and one row, `empty`. It
demonstrates an empty portfolio without inventing brokerage columns. Build and install the wheel
beside `marketsieve-cli`, then select it with `--broker example-portfolio`.

This example is documentation and distribution-test input; it is not published by this repository.
