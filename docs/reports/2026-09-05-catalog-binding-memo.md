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
