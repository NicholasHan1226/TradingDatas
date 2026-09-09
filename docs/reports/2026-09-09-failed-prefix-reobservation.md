# Failed-prefix reobservation (2026-09-09)

## Frozen contract, threat model, and stopping line

A real identical append-only provider reobservation may rebind only a row whose
original receipt belongs to a validated execution with an explicit terminal
failure. Preserve healthy first-success provenance, immutable payload/row key,
and revision. Record the new observation as unchanged and update only receipt_id
and collected_at in the same transaction as the new receipt. Receipt failure
must roll back the provenance update. Apply this to both identical-content and
registry-derived metadata-drift unchanged branches.

Missing, malformed, foreign, or incomplete evidence is not repair authority.
Do not trust JSON labels, current catalog success, or a latest unrelated receipt.
Use the existing bounded receipt/execution validators and transaction-local
memoization; do not scan the complete journal per row. Do not alter query failure
filtering, schemas, provider budgets, activation, or existing API/PIT contracts.
No production SQL repair: recovery requires another genuine provider observation.

Stop after the smallest shared storage fix and focused synthetic tests covering
failed-prefix recovery with query proof, healthy provenance, invalid/incomplete
history, both unchanged paths, and receipt rollback. Production release and real
receipt/query acceptance remain the owner task's separate responsibility.

## Implemented candidate and verification

`storage/provider_dataset_rows.py` now validates the original receipt and its
bounded execution cohort using the existing receipt projection helpers. A
variant must have an actual failed terminal: a failed attempt superseded by a
successful retry does not qualify. The receipt must match the fact's provider.
The per-write memo avoids repeating the same old receipt/execution validation
for every unchanged row. Both append-only unchanged branches share the check.
Healthy or merely incomplete variants retain their first provenance; malformed,
missing, foreign-provider and call-gap evidence rejects the transaction.

The synthetic regression uses real SQLite admission/ingest transactions and an
E+O old configuration followed by an E-only configuration with a different hash.
It verifies unchanged counts, unchanged payload/revision, new collected_at and
receipt, then queries the physical database with row receipt proofs enabled.
Only dataset runtime projection uses the existing synthetic fixture; row proof
validation and filtering are real. The metadata-drift branch, healthy old-config
provenance, incomplete variants, malformed/missing/call-gap/foreign evidence,
failed-then-successful retry, and receipt failure rollback are covered.

Validation on the final candidate: **63 passed in 5.83s** across
`tests/test_failed_prefix_reobservation.py`, `tests/test_provider_dataset_rows.py`,
and the existing failed-cohort filter, successful retry, and append-only as-of
overlap query regressions. Ruff and `git diff --check` passed. No collector,
public API, registry, STATUS or OPERATIONS changes were required in this patch.
No production operation, commit or push was performed by the collaborator.

The owner must independently review, run required CI, release the candidate, and
perform a budgeted real E-only reobservation before claiming production recovery.
Verify non-empty authenticated query rows and their new receipt IDs, not catalog
row count alone. Rollback is the prior release; existing immutable receipts are
retained and no schema migration or direct production database edit is involved.

Independent review found a same-batch duplicate edge case: a second identical
row could look up the new receipt before the batch inserts it. The final guard
uses only identities already recorded in this transaction's expected-row
readback map; it does not exempt arbitrary matching receipt IDs. Fresh insert
and failed-prefix recovery batches containing duplicate payloads now preserve
exact inserted/unchanged counts and one fact/one new receipt, covered by two
additional regression cases.
