# Account retention and deletion v1

Owner approved on 2026-08-30 by “继续执行以上”: expired OTP records removed
within 24 hours, invalid sessions within seven days, profiles retained until a
user requests deletion and removed within 30 days thereafter. These are maximum
times, not minimum retention periods. This candidate targets earlier hourly
cleanup. It is not deployed and does not establish an operational SLA.

## Boundary and contract

- Only the dedicated account `IDENTITY_DB`; never financial facts, ingest
  receipts, legacy API keys, Resend mail history, or other projects' databases.
- `POST /api/account/profile/deletion` accepts only the current authenticated
  email identity, a same-origin JSON request with `confirmation: "DELETE"`,
  and a session verified within the last ten minutes. The client cannot choose
  a user ID. No API-key or administrator deletion endpoint is introduced.
- Within one D1 batch, revalidate the session, queue an explicit user-owned
  deletion request, disable the user and revoke every email session. Return
  acceptance only after commit. A service failure is not a deletion receipt.
- Already disabled profiles are not automatically deleted. Only a queued,
  disabled profile qualifies. No paid tenant/admin grants exist in this slice;
  future linking MUST revise deletion to revoke dependent authority before
  exposing it to linked users. Do not carry this unsubscribed-only contract
  into a future linked-account implementation unchanged.
- The hourly scheduled handler deletes expired challenges, expired/revoked or
  disabled-user sessions, expired rate/cooldown buckets, and explicitly queued
  disabled profiles with their email challenges/sessions. Batch bounds and
  aggregate backlog indicators prevent unbounded work or false completion.
  Repeating a run is safe. Never log addresses, IDs, cookies, codes or raw SQL
  errors. A failure/backlog is visible as a failed scheduled invocation.
- Re-registration after completed deletion creates a new identity and restores
  no previous authority. Bookmarks remain browser-local, not part of D1 deletion.

## Release, limits and rollback

`IDENTITY_RETENTION_ENABLED` remains false in the candidate config; the hourly
`17 * * * *` schedule is not live until reviewed deployment. With the flag off,
maintenance does nothing and the deletion action is unavailable. Email login
also remains false. Apply the additive `worker/identity-retention-schema.sql`
to the dedicated account store only after exact-target approval. It creates one
empty request table and index, never rewrites the original five tables. Local
tests apply both schema files to disposable stores.

Before activation, verify the binding, additive schema, scheduled execution,
zero backlog, failure visibility and rollback against an isolated store; then
verify the real deployed boundary. Disabling new login must not disable cleanup
or revocation. Disable the retention flag only as an incident rollback and
manually clear any queued requests within the approved deadline. Keep the
additive table on rollback; do not drop records or restore deleted users.

The policy describes deletion from the active identity store. Cloudflare backup/
Time Travel and Resend delivery-log retention must be independently verified and
documented before making an all-copies deletion promise. No user export or new
backup is created by this change. Platform scheduled failures/backlog must be
reviewed before claiming the 24h/7d/30d operational deadlines are met.

Verification: `cd public-web && npm run build && npm run test:sites`, plus
`node scripts/check-email-runtime.mjs <installed-miniflare-module>` for actual
local workerd/D1. Browser tests use example.com fixtures only.

References: [D1 atomic batches](https://developers.cloudflare.com/d1/worker-api/d1-database/#batch),
[Scheduled handlers](https://developers.cloudflare.com/workers/runtime-apis/handlers/scheduled/).
