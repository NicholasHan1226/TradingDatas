# Catalog receipt validation memo follow-up

Scope: remove duplicate validation of the same receipt under an unspecified binding
and its resolved matching owner binding. No schema, index, provider, timeout, worker
capacity, raw receipt or read-clock contract changes. Existing malformed/wrong-binding
failures remain unchanged. Rollback is the prior source implementation; runtime
switches must still use the verified immutable release procedure.

Validation: 238 receipt projection tests passed. Matching None/binding validation
calls reduce from two to one. Two bounded 192-dataset production-snapshot projection
comparisons used a fixed clock and exact result equality. Baseline-first seconds:
7.8274/1.7558 baseline cold/warm, 3.2680/1.6088 candidate. Candidate-first:
6.6493/2.3630 candidate, 3.6816/1.5066 baseline. Cache order and storage load dominate;
these are projection-only measurements, not full catalog latency or an SLA claim.

A fresh immutable a093d407 profile took 23.923 seconds including profiling overhead;
coverage aggregation accounted for 12.063 seconds and receipt projection 11.556.
Exact coverage counts remain I/O-sensitive; do not replace them with estimates or
increase the existing 15-second target. Source review independently confirmed
binding/error equivalence. Production cut and full authenticated cold catalog
readback are separate pending steps; STATUS records their eventual outcome.

## Merged candidate and runtime readback

PR #494 merged as `3a2e534091079e28d1955ee0a2fca8c1bb1c2590`;
exact-main CI 33964421197 passed. Both staged release manifests verified 1071
files. On September 5 at 19:59 Asia/Shanghai, an isolated candidate process
returned the real authenticated A-share catalog: 200, 16.251 seconds, 192 datasets.
Crypto initially exceeded the diagnostic launcher's short readiness wait; after
allowing normal initialization (without changing production initialization or
HTTP limits), its first authenticated catalog returned 200, 11.576 seconds,
240 datasets. This was a diagnostic wait issue, not evidence of a production outage.

The A-share result does not meet the existing 15-second target. No data runtime
cut was performed; both live pointers remain `a093d407d23fe6cf7f82c1fb2a27359c82b7d803`,
with 1056-file manifests verified. Candidate processes were reaped independently;
no live service, timer, database content or credential was changed.

At 20:08, live internal readback returned A-share 200/16.433s/192 and Crypto
200/6.973s/240, with identical dataset identity digests to the candidate.
The one-row `cn.dataset.fina_mainbz` query returned 200/0.286s, partial/degraded
and complete SQLite receipt lineage. These are internal reads, not an ordinary
customer test, cold-start acceptance or a continuous SLA. Performance release
remains incomplete; source-quality states and public account delivery are separate.
