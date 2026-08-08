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
and release gates. The executable coverage floor is 80 percent across the supported workspace. A
reviewed commit is immutable evidence; later commits require another review.
