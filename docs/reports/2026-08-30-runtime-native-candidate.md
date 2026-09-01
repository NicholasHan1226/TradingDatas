# Crypto native candidate matching follow-up — 2026-08-30

## Production evidence that requires another change

PR #403 merged as `855cec1e8b58d636af011c53194b199cf57c1e0e`; candidate CI
33318342477 and exact-main CI 33318813553 passed. At 23:21 CST the real target
returned the same paused-writer 240 catalog rows and six query data/selected
metadata summaries as 4bb. Single catalog took 12.050 seconds. Both simultaneous
catalog requests timed out at 15.017 seconds, so the release was rejected.
Rollback authenticated readback completed at 23:22:24, retained the same summaries,
and restored seven original timers. At 23:24:33 the actual PID/cwd and immutable
manifest again identified Crypto `4bb6fe8` (WAL), while A-share core remained
`c714dc9`; the independent existing admin deployment channel was on `855cec1`.
No collector was killed, no fact/receipt/schema or journal mode changed.

## Frozen candidate contract

Optimize only the existing literal byte prefilter, not receipt authority or
raw scan budget. For a bounded UTF-8 shared-prefix/suffix set:

1. No prefix occurrence returns false without entering Python.
2. A matching exact suffix at the first occurrence returns true.
3. If that occurrence misses but another prefix exists starting at first-position
   plus one byte, call the original complete Python matcher. This preserves later,
   overlapping, nested, malformed, invalid-UTF-8 and after-NUL matches.
4. Otherwise return false. SQL NULL retains the existing non-match semantics.

Native SQL and parameters must be bounded (32 KiB and 800 parameters, respecting
lower actual connection variable limits and reserving source/LIMIT parameters).
If the optimization cannot fit, use the original path; do not reject a previously
valid call. No-prefix/highly-variable patterns and non-UTF-8 retain their existing
fallback. Keep unique UDF ownership, cleanup, the process-local reentrant scan
lock, every raw-row budget charge and the existing classifier/execution parser.

A cross-request projection cache is deliberately excluded. Existing database
epoch summary statistics can collide on same-length receipt rewrites, and a
new connection's data_version does not prove shared snapshot identity.

## Same-request seed reuse extension

Native matching alone kept real-database full responses and all 20,000 raw sibling
rows identical, but warm two-reader diagnostic timing was 13.678/13.659 seconds.
A fresh native profile counted zero Python matcher calls, yet repeated physical
attempt parsing still took 2.069 seconds over 20,001 calls. That measured gap
reopened the candidate before commit/release rather than relaxing acceptance.

While validating a dataset's recent seed rows in one catalog request, retain an
optional mapping of the complete raw SQLite tuple (including typeof fields) to
its already-classified seed and validated execution identity. Sibling SQL still
reads every original candidate and charges the original budget/limit first.
Only an exactly identical raw tuple may reuse that seed; new, altered, invalid or
unrecognized rows follow the unchanged classifier and parser. Execution membership
is still checked. The mapping is limited to that dataset's at-most-100 current
seeds and is discarded with the request; it is neither a cross-request cache nor
a substitute for fresh SQLite reads or receipt validation. Other scanner callers
retain the default path. No global parser memo is introduced.

## Verification and release boundary

Frozen combined source SHA256 is
`4a8536e84860e7e67c19783217ab77bb89bcabf962a08cede1a94569099b1161`.
Independent review found no P0/P1 and independently passed 53 focused checks
(20.25s), including native/fallback, lock cleanup, seed mutation, invalid rows,
budget charging and cross-request isolation. Source/test hashes stayed unchanged.
The native-only predecessor passed 295 regression tests and a 37,806-row literal
predicate differential across three encodings; these are not a combined-suite claim.

On the combined candidate, one verified real database snapshot returned exactly
the same full 240-row response and 200 groups/20,000 raw sibling rows as the
baseline. Cold baseline/candidate took 10.158/10.356s; candidate warm took 5.782s.
Two independent warm reads took 12.747/13.661s. Those timings remain close enough
to the gate that actual paired HTTP acceptance is mandatory. These experiments
ran as the existing Crypto UID with zero provider calls/database writes and
synthetic local grants; they are not HTTP/authenticated production evidence. Do not publish unless independent review,
exact candidate CI and real merged-main CI pass. Reuse the reviewed WAL-preserving
maintenance: original seven timers only, natural collector drain, original two
locks, immutable release/PID readback, identical paused-writer data, and two real
simultaneous authenticated catalog requests each below 15 seconds. Failed
acceptance rolls back to 4bb/WAL, never the old 15f/DELETE path. Natural receipt
advancement and actual consumer credential readback remain separate checks.

Short-SLA refresh stays default zero until current QuickSync daily quota evidence
exists. No new provider, dataset, timer, credential, trading workflow or route.
Evidence stays outside Git in `work/runtime-reliability-20260830/`; this report
records evidence available at candidate freeze; subsequent exact CI and runtime results
belong in the PR readback record and owner-facing execution report.
