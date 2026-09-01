# Resumable history scope repair

Base: `e2e6d9f7a17c64cbb44c58fe3d7f02ec66754177` (merged #388).

The 11:52:24–12:00:16 CST production round completed 15 datasets with zero failed
terminal results, including an empty income receipt and a successful pledge-stat
receipt. It nevertheless exceeded the five-minute release gate: approximately
eight minutes elapsed and 6m6.241s CPU. The runtime was rolled back to verified
`79c33f9`, preserving all facts and receipts. A sampled wait on Firecrawl proves
only part of the elapsed time; it is not evidence that all CPU time was upstream
latency. The independently deployed patrol is outside the data runtime pointer.

`_resumable_histories` called `validated_receipt_histories_by_dataset` for every
resumable dataset and discarded all entries except its own. This repeatedly
scanned and validated the whole registry, including unrelated histories, for
each newly scheduled report-family fanout.

The patch reuses the existing `validated_receipt_history_for_dataset` function.
It uses the same complete target-history authority validator and snapshot
boundary. No receipt schema, config hash, provider call, budget, timer, dataset
activation, credential, or database content changes. There is no persistent
cache or weakened validation.

Three regressions first reproduced unrelated history scans, then passed after
the change: equal trusted results for a healthy target, equal results with an
unrelated corrupt history, and fail-closed rejection of a corrupt target. Each
also asserts exactly one dataset authority scan. Adjacent tests and live bounded
read-only timing are recorded with the candidate PR; they do not replace the
post-release natural-round timing and authenticated catalog/query gates.

Rollback remains the verified previous immutable runtime. Do not redeploy solely
because a local benchmark improves. The relay outage, historical month-quality
markers and unproven continuous provider cadence remain independent gaps.
