# Quality

## Matrix acceptance

Synthetic calculation tests cover minimum observations, boundary windows, zero denominators, date
alignment, missing benchmarks, overlapping memberships, and deterministic content identity. Every
defined field must be present in exactly one of a row's value or missing maps.

Adapter contract tests mock multi-symbol price DataFrames, company information, financial
statements, empty responses, rate limits, retries, and partial failures. A separately marked live
smoke selects Japanese and U.S. securities plus all five benchmarks and runs only when explicitly
enabled.

Integration tests verify:

- one row per unique constituent and one common field catalog;
- JSONL and CSV row and value agreement;
- empty CSV cells plus `missing_fields_json` reason preservation;
- self-contained HTML with all fields and no external resource;
- stable missing codes, resume fingerprint enforcement, and schema validation;
- offline row and comparison reads with no calculation or provider access;
- absence of removed screen, inspect, indicator-analysis, and old comparison commands;
- absence of `.xlsx` and other Excel outputs.

## Data quality

Readiness is a quality observation, not a license to discard rows. All constituent rows remain in a
partial matrix. Overall and per-index price coverage are calculated from explicit price success,
while field- and reason-level missing counts expose financial and classification limitations.

The index summary reports only reproducible aggregate statistics. Analyses distinguish observed
facts from interpretation and do not turn missingness or outliers into unrecorded corrections.

## Repository acceptance

The complete gate runs formatter check, lint, strict type checking, import-boundary validation,
structure tests, the full test suite with at least 90% line coverage, schema validation, reproducible
offline smoke checks, secret scanning, package builds, isolated installation, and external plugin
compatibility checks.
