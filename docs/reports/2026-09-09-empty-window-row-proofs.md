# Empty-window row receipt proofs: frozen candidate

Base: 2cac86449a01b8eced5b1e685a6cf763c38686b4.

Production read-only reproduction on physical 9dabe0bb, as tradingdatas using
its existing interpreter/environment and the verified SQLite reader: filters={},
schema_major=1, limit=5 returns two ci_index_member/index_member_all rows without
proofs. Enabling proofs fails at query_service.py:989 because it unconditionally
rejects an empty request_window. cb_rate/stk_rewards/top10_holders reproduce the
same rejection; fund_adj has a date window and succeeds with or without proofs.
No provider call, database write, service change or credential output was used.

Frozen boundary: only accept an empty proof window when its unique active
provider binding explicitly has no request-window policy and no template window
reference. For empty windows on windowed bindings reuse dataset_registry.normalize_request_window
to reject the missing required keys. Nonempty historical proof handling is unchanged. Keep the
session-minute special contract and all existing row receipt authority and
single execution/window/config/data_through restrictions. No schema, activation,
provider budget, API route or query gate expansion. Unknown provider and missing required windows cannot use this exception. Existing
nonempty-window and malformed receipt validation is not expanded or bypassed.

The five production failures share the empty-window check, but a later failure
from mixed cohorts remains a valid independent constraint; do not describe all
five as recovered without real readback. Limit 1 can isolate a valid proof;
ci_index_member/index_member_all have two rows from the same new receipt and
provide the bounded multirow case. fund_basic after genuine recovery should
likewise have a common new receipt, and needs separate production acceptance.

Stop after the minimal shared formatter fix and tests proving equal data with
proofs false/true for legitimate on-demand empty windows, existing fund_basic
contract compatibility, required-date/partition-mismatch/foreign rejection, and
preservation of single-cohort and minute boundaries. Owner handles publishing
and authenticated readback; this collaborator does not commit or deploy.

## Final candidate validation

The final code changes only the former unconditional empty-window rejection;
nonempty historical proof and partition handling remains unchanged. New tests
cover proof/no-proof data parity on a valid on-demand contract, required empty
window rejection, template placeholder without policy rejection, foreign binding,
existing partition mismatch, mixed execution rejection, and the checked-in
fund_basic / ci_index_member / index_member_all no-window contracts. An explicit
regression preserves the existing historical nonempty-window/no-current-policy
behavior; this patch does not reinterpret old request contracts.

Final scoped suite: **99 passed in 62.44s** across new empty-window tests, the
complete provider-native query suite, and failed-prefix reobservation tests.
The subsequently added historical nonempty compatibility regression passed
separately (**1 passed in 2.24s**). Ruff and git diff --check passed. No commit,
push, provider call, production database write or service action was performed.
Production recovery and whether larger proof pages span cohorts remain unverified
until the owner publishes and performs authenticated readback.
