# Lifecycle

A Market Snapshot run begins with explicit immutable inputs. It writes a resumable run request,
acquires source evidence, calculates fields, writes a pending object, verifies every projection,
atomically publishes the content-addressed object and latest reference, then removes the run.

A Security Research run resolves a verified Snapshot row, acquires explicit evidence domains,
writes and verifies one immutable object per successful instrument, and reports per-instrument
failures. Objects are never updated in place.

A close Capture returns `capture-run/v1` state with a deterministic run ID, status, exit code, and
resume capability. An identical market, session, date, input, asset, setting, definition, producer,
Snapshot schema, and Explorer schema request resolves to an existing immutable object as a duplicate
instead of reacquiring it. A producer or projection contract change creates a new object without
rewriting the old object. JP and US price dates remain separate evidence and are never presented as
one hidden common timestamp.

Historical objects remain addressable by ID. Diff compares only fields with compatible type, unit,
and definition version. Cleanup may remove caches, interrupted obsolete runs, build evidence, and
legacy pre-0.12 local state only after new objects are verified.
