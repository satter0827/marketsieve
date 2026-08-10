# Quality

Pure calculations test observation boundaries, zero denominators, date alignment, benchmark gaps,
overlapping memberships, and Decimal determinism. Provider contract tests mock DataFrames, company
facts, statements, events, empty responses, rate limits, partial failures, and corporate-action
inconsistency.

Storage tests verify content identity, canonical JSON/JSONL, complete inventories, object-local
Explorer references, absent spreadsheet artifacts, deterministic query order, compatible diff
fields, resume fingerprints, and tamper detection. Preview tests verify that only
manifest-registered files are served. Research quality reports independent evidence-domain states:
`available`, `partial`, `none_observed`, `not_requested`, `acquisition_failed`, `not_applicable`,
or `temporally_misaligned`. A failure is assigned only to its affected domain; for
example, an earnings endpoint failure does not invalidate acquired dividend or split events.
Live smoke tests are explicit and separate from the default offline suite.

The local development gate runs independent quality, test, package, and smoke lanes with bounded
parallelism. `GATE_JOBS=0` selects at most four workers and `GATE_JOBS=1` is the deterministic
serial fallback. Gate evidence records task duration and worker count without making elapsed time a
pass/fail threshold.

Release handoff requires format, lint, type, test, full development, package build, isolated install,
and release gates. Coverage includes product packages and `scripts/`, excludes tests from the
denominator, and erases prior data before measurement. The floors are 85 percent statements,
75 percent branches, and 80 percent statements for critical Market, Research, storage, release,
review, governance, and gate modules. Evidence records the commit, configuration hash, and measured
targets. A reviewed commit is immutable evidence; proven descendant changes use a delta semantic
review, while discontinuous history requires a new full review.

Release qualification names all evidence explicitly. It requires three unique consecutive close
sessions for each exchange, current RC-produced Snapshots with the standard scope and passing
quality gates, independently verified Research Packs from both final Snapshots, loopback Preview,
healthy artifact inventory, exact Market cancellation and resume fingerprints, and retained
Research publication after cancellation. Provider partial failures remain acceptable only when
they are explicit and pass the artifact quality contract. Corruption, reconstruction, duplicate
sessions, concealed missing evidence, or manual repair fail qualification.

Snapshot and Research objects separate `quality-summary.json`, `quality-details.jsonl`,
`quality-outliers.jsonl`, and `failures.jsonl`. Normal missing values and `not_applicable` remain
with their security row; outlier candidates retain rule, population, threshold, severity, and value
origin without modifying the authoritative value.
