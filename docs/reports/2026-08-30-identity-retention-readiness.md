# Account retention and deletion readiness — 2026-08-30

Scope: owner-approved continuation of email identity PR #397. The owner approved
the previously proposed 24h / 7d / 30d active-store maxima. Existing branding,
public Account and language rules are retained. Payments and SMS remain off.

Follow-up: [2026-08-31 mobile and identity-refresh review](2026-08-31-identity-mobile-readiness.md)
supersedes the responsive harness limitation and records the remaining explicit
final-deletion UI approval boundary. This report remains the earlier checkpoint.

## Candidate changes

- Additive request queue in the dedicated identity DB; no remote SQL executed.
- Self-only `POST /api/account/profile/deletion`, exact confirmation, same origin
  and an email session verified within ten minutes. Atomic acceptance disables
  the profile and revokes every email session; no caller-supplied target identity.
- Bounded hourly cleanup for expired OTP/session/abuse-control records and
  explicitly requested disabled profiles. Unrequested disabled users are retained.
  Failed transactions preserve the request; backlog cannot report success.
- Existing Account → Security has inline confirmation, cancel, pending, fresh-
  verification failure and unconfirmed-result states. Only accepted responses
  clear local account state. No new dashboard or fake completed-purge message.
- Both `EMAIL_LOGIN_ENABLED` and `IDENTITY_RETENTION_ENABLED` remain false.
  Deployment must separately apply/review the additive schema and enable the job.
  The local responsive harness adds a disposable 390/768px iframe view; it is not
  bundled or served by the production Worker.

## Fresh local evidence

- `npm run build` passed; generated client/server artifacts included.
- `npm run test:sites`: **109/109 passed**, including expiry boundaries, preservation
  of active sessions and unrelated users, missing/repeatable migration, atomic
  deletion failure/retry, backlog, accepted-response validation and sanitized
  scheduled failure handling. All identities and mail in tests are synthetic.
- Actual local workerd/D1 runtime: challenge/atomic verification, unsubscribed
  isolation, accepted self-deletion, revoked-session rejection, scheduled profile
  purge, and legacy redirect rejection passed. No outgoing real mail allowed.
- Wrangler 4.127.1 generated runtime/binding types into a temporary directory;
  `deploy --dry-run` validated packaging/bindings without publishing. Its generic
  Node types installation hint was not acted on; no dependency/lockfile changed.
- Independent read-only review found no P0/P1 defect. Additional disposable SQLite
  probes verified revocation between read/transaction, concurrent deletion with
  one acceptance, and cleanup independent of email-login enablement. A P2 pending-
  deletion/sign-out UI gap was fixed by disabling that button while submitting.
- Browser: synthetic email login, Security, incorrect confirmation disabled,
  cancel, Chinese/dark and English/light presentation, accepted deletion and signed-out state passed.
  Desktop DOM width/scrollWidth both 1280px. A real 390px nested viewport rendered
  Account overview; its full deletion keyboard flow was not established through
  the current browser frame-control surface and is not counted as passed.

## Release and remaining boundaries

The branch integrated main `855cec1` through merge `522d6f5`; this does not claim
new verification of that main commit's financial runtime. Updated candidate CI
and Datas PM `pm-merge` remain separate release gates. Current source/build/test
evidence is local; remote PR check results should be read from the exact candidate.

No production migration, cleanup, credential change, new mail, user deletion,
administrator grant, tenant association, payment/SMS activation or deployment
occurred in this follow-up. Browser mock accounts were created/deleted only in
memory. Remote identity DB still needs the reviewed additive schema before use.

Remaining before launch: private sender/pepper provisioning, exact-head approval,
real OTP session test, real scheduled failure/backlog visibility, backup/Time Travel
and mail-log retention review. Existing delivery-test receipts are not OTP proof.
Administrator/shared sign-in and explicit subscription linking are later separate
contracts, and must extend deletion to revoke their dependent authority first.

Rollback: stop new login without disabling maintenance/revocation; preserve queued
requests and the additive table. Any maintenance rollback needs manual account-only
fulfilment inside approved deadlines. Never restore deleted users or touch legacy
keys, data-plane facts, receipts or other projects. Operational SLA is unverified.

Contracts: [Account retention](../design/identity-retention-v1.md),
[Email identity](../design/email-identity-v1.md), [API](../API.md),
[Operations](../OPERATIONS.md). No new security-scan clearance is claimed: the prior
formal scan's coverage was partial and predates this retention patch.
