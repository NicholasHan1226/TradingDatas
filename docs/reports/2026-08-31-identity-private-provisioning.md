# Private account-service preparation — 2026-08-31

Scope: Nicholas explicitly confirmed completing the dedicated sender/identity
secrets and the account-only deletion-request schema. This is preparation, not
approval to merge PR #397, deploy its code, enable login/retention, send email,
grant roles or subscriptions, or touch financial-data services.

## Target and preflight

- Worker: `tradingdatas`, Cloudflare account `1f049ae7407c623d20349e5a916b85d5`.
- Dedicated D1: `tradingdatas-identity-v1`, ID
  `bb5e8d90-090f-40a5-9aa1-b91b33af7199`.
- Resend connector domain: `account.tradingdatas.com`, ID
  `06e2de82-4db8-4ab2-9d9f-219cd647990c`; verified, sending enabled,
  receiving/open/click tracking disabled. The existing unrelated `Onboarding`
  key must remain unchanged. Browser and connector workspaces differed; no
  browser-side configuration was changed.
- During the 2026-08-31 18:51–18:57 CST preflight, D1 had the original five identity tables,
  zero users/sessions/challenges, and no foreign-key violations.
- Live Worker version: `6f42cdec-0351-4431-93cc-1e111e751ed0` (100% traffic);
  existing `SESSION_ENCRYPTION_KEY` only, no identity binding or scheduled handler.
- Candidate source: `337d9f3ae0e31946937411495a78f3ba4e7ec485`; PR #397 open,
  no `pm-merge`. Targeted identity/retention tests passed 28/28 this turn.

## Approved operations and rollback boundary

Apply only `public-web/worker/identity-retention-schema.sql`, SHA-256
`87dfeb1faa5778513c7b1a4d67bac1f2934b90bec2e5b270ffb6624d5f112cb2`.
It adds an empty request table and index without rewriting the five existing
tables. Retain this additive structure on rollback; no records are to be deleted.

Create one domain-restricted sending-only key for TradingDatas and a securely
random identity pepper. Transfer values privately to a **non-deployed Worker
version**, preserving the existing session secret and code. Do not output secret
values, write them to source/files, enable flags, or shift production traffic.
If provisioning fails, inspect the named key/version before retrying; never
blindly create a second key or delete unrelated credentials. Rollback is to leave
the candidate version undeployed, not rotate existing production credentials.

## Execution and readback

The approved additive migration executed its two statements successfully.
`identity_deletion_requests` has `user_id TEXT PRIMARY KEY` referencing
`identity_users(id)` and `requested_at INTEGER NOT NULL`; the timestamp index is
present. Users, sessions, challenges and deletion requests all remain at zero.
`PRAGMA foreign_key_check` returns no violations. No user data was created or deleted.

At `2026-08-31T10:56:47.353075Z`, Resend created the dedicated
`TradingDatas account login` key (`24ad44c4-65f1-4878-989a-c9ff922617da`), with
`sending_access` restricted to the verified domain above. The key list was read
back with exactly that new key and the unchanged `Onboarding` key. No email was sent.

Both new credentials were passed through private process stdin, never command-line
arguments, source files, documents or chat. `IDENTITY_PEPPER` uses 48 random bytes
(64 base64url characters). Transient sender material was cleared after readback.

Cloudflare version **`2b64f7d6-5b47-41c7-b704-b156abcc5a05`** was created at
`2026-08-31T10:56:56.096951Z`, tagged `identity-secrets-prep`, and **not deployed**.
Version readback lists `RESEND_API_KEY`, `IDENTITY_PEPPER` and the preserved
`SESSION_ENCRYPTION_KEY` as `secret_text`. Values are not readable. Its script ETag
`95aec9a9e2e2088b6b626a71bf2950b949ed914581ea42976c7152b2b31736b9`
matches the previous live version. This old-code version has only a fetch handler;
it has no identity DB binding or scheduled handler. Candidate source/config was
not uploaded by the secret operation.

The live deployment remains `a856034c-ef03-4e0d-8303-f32ed88aadb0`, with 100% traffic
on `6f42cdec-0351-4431-93cc-1e111e751ed0`. Login and retention were not activated.
Wrangler's initial log-to-`/dev/null` setting caused a directory-warning; upload
still exited successfully and was independently read back. No credential file was
created. Future private provisioning must use `WRANGLER_WRITE_LOGS=false` and
`WRANGLER_LOG_SANITIZE=true`, not use `/dev/null` as a log directory.

## Remaining release work

Do not deploy the old-code secret-preparation version as the email implementation.
A later approved exact-source release must explicitly preserve the prepared
secrets and verify the D1 binding, disabled/approved flags, code, session behavior
and template-based delivery. Verify the target version's binding names before
traffic switching; do not assume staged secrets automatically survive another
deployment. The prepared version is not production credential activation.

PR #397 still needs exact-head CI and Datas PM `pm-merge`, followed by separate
exact-source release approval. Live OTP delivery, expiry/replay, session isolation,
revocation and scheduling remain unverified. Payment, SMS, role grants, key linking,
financial-data databases and collectors were not changed.

## Validation

- `npm run test:sites`: 111/111 passed after the documentation update; the
  earlier targeted email/retention subset also passed 28/28. No app source,
  generated build, dependency or local Worker configuration changed this turn.
- Live read-only checks: `/login` returns 200 with the TradingDatas HTML;
  `/api/account/auth-methods` still returns 404 `not_found`;
  unauthenticated `/api/account/me` returns 401 `unauthenticated`.
  These confirm the existing public boundary, not successful email sign-in.
- Active-deployment metadata, the staged version's script ETag and secret binding
  names, and D1 schema/counts were read independently. No real-mail send or
  authenticated customer/administrator request was made.
- `git diff --check` passed. UI rendering was not repeated because no visible
  UI or application code changed; prior mobile/readiness evidence is linked in
  [the candidate review](2026-08-31-identity-mobile-readiness.md).

References: [Cloudflare secret version semantics](https://developers.cloudflare.com/workers/configuration/secrets/),
[identity contract](../design/email-identity-v1.md),
[retention contract](../design/identity-retention-v1.md),
[earlier account-store initialization](2026-08-30-email-identity-provisioning.md).
