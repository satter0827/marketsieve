# Lifecycle

A Market Snapshot run begins with explicit immutable inputs. A UUIDv7 `operation-run/v1` records
the command, fingerprint, status, events, failures, timing, and published object IDs. Acquisition
writes a separate resumable run request. If acquisition stops before publication, the operation
record is marked resumable and carries the exact 16-character acquisition `resume_run_id`; the CLI
error prints the matching `marketsieve market build --resume TOKEN` recovery command. Acquisition
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

Research v9 objects are immutable and intentionally incompatible with earlier Research contracts.
Changing the requested evidence or source response creates a new content identity; changing only
the Explorer display period does not create or mutate an object.

Historical current-contract objects remain addressable by ID. Artifact inventory isolates
incompatible, corrupt, and orphan state so one entry cannot prevent current objects from being
listed. Diff compares only fields with compatible type, unit, and definition version. Snapshot v9
and Research v9 readers reject earlier object contracts with rebuild guidance. They do not migrate,
reinterpret, or delete those objects. Cleanup may remove caches, interrupted obsolete runs, and
build evidence only through an explicit operation.
