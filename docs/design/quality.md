# Quality

Pure calculations test observation boundaries, zero denominators, date alignment, benchmark gaps,
overlapping memberships, and Decimal determinism. Provider contract tests mock DataFrames, company
facts, statements, events, empty responses, rate limits, partial failures, and corporate-action
inconsistency.

Storage tests verify content identity, canonical JSON/JSONL, complete inventories, self-contained
HTML, absent spreadsheet artifacts, deterministic query order, compatible diff fields, resume
fingerprints, and tamper detection. Live smoke tests are explicit and separate from the default
offline suite.

Release handoff requires format, lint, type, test, full development, package build, isolated install,
and release gates. Coverage includes product packages and `scripts/`, excludes tests from the
denominator, and erases prior data before measurement. The floors are 85 percent statements,
75 percent branches, and 80 percent statements for critical Market, Research, storage, release,
review, governance, and gate modules. Evidence records the commit, configuration hash, and measured
targets. A reviewed commit is immutable evidence; proven descendant changes use a delta semantic
review, while discontinuous history requires a new full review.
