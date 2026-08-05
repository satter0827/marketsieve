# MarketSieve SEC Source

Explicit, read-only acquisition of SEC EDGAR submissions and company facts for one CIK. The source
uses no API key. Set `SEC_USER_AGENT` to an organization and contact email accepted by the SEC fair
access policy, and configure the ten-digit CIK explicitly. The user-agent value is sent only as an
HTTP header and is not stored in snapshots or results.

The adapter reads the official `data.sec.gov/submissions` and `api/xbrl/companyfacts` JSON
resources. It retains accession numbers, acceptance times, amendment relationships, fiscal
periods, taxonomy, units, and fact-to-filing links. It does not download filing documents, evaluate
custom taxonomies, infer a CIK from a ticker, or make an investment decision.
