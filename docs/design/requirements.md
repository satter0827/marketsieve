# Requirements

- **MKT-01:** Every build selects at least one explicit index scope and evidence domain.
- **MKT-02:** yfinance is the only runtime market-data source and needs no key or registration.
- **MKT-03:** Every constituent appears once by `MIC:SYMBOL`, including failures.
- **MKT-04:** Missing values are not imputed and have stable reason codes.
- **MKT-05:** Snapshot identity includes exact inputs, settings, source evidence, and failures.
- **MKT-06:** Query, row, comparison, and diff are stored-data-only operations.
- **RES-01:** Research instruments and evidence domains are explicit per invocation.
- **RES-02:** Research remains linked to an exact source Snapshot.
- **RES-03:** A batch preserves successful packs when another instrument fails.
- **ART-01:** JSONL is authoritative; HTML and Markdown are deterministic projections.
- **ART-02:** Every object is self-contained and has no external runtime or file reference.
- **ART-03:** Excel and CSV artifacts are never generated.
- **ART-04:** Artifacts contain no prompt, reasoning template, score, ranking, or recommendation.
- **ART-05:** Every machine document is validated by a schema shipped in the CLI before publication
  and whenever an immutable object is read.
- **OPS-01:** Operational settings and invocation inputs are structurally separate.
- **OPS-02:** Public CLI entries are limited to market, research, operations, doctor, and
  capabilities.
- **OPS-03:** Formatter, lint, type, test, package, installation, and release gates must pass.
- **OPS-04:** Releases use GitHub Releases only and install on macOS and Ubuntu with Python 3.12
  through 3.14.
