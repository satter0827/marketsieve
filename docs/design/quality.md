# Quality

Pure calculations test observation boundaries, zero denominators, date alignment, benchmark gaps,
overlapping memberships, and Decimal determinism. Provider contract tests mock DataFrames, company
facts, statements, events, empty responses, rate limits, partial failures, and corporate-action
inconsistency.

Storage tests verify content identity, canonical JSON/JSONL, complete inventories, object-local
Explorer references, absent spreadsheet artifacts, deterministic query order, compatible diff
fields, resume fingerprints, and tamper detection. Preview tests verify that only
manifest-registered files are served. Research quality reports independent evidence-domain states:
`available`, `none_observed`,
`not_requested`, or `acquisition_failed`. A failure is assigned only to its affected domain; for
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
