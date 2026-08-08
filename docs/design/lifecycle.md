# Lifecycle

A Market Snapshot run begins with explicit immutable inputs. It writes a resumable run request,
acquires source evidence, calculates fields, writes a pending object, verifies every projection,
atomically publishes the content-addressed object and latest reference, then removes the run.

A Security Research run resolves a verified Snapshot row, acquires explicit evidence domains,
writes and verifies one immutable object per successful instrument, and reports per-instrument
failures. Objects are never updated in place.

Historical objects remain addressable by ID. Diff compares only fields with compatible type, unit,
and definition version. Cleanup may remove caches, interrupted obsolete runs, build evidence, and
legacy pre-0.12 local state only after new objects are verified.
