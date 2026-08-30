# Email identity inside the existing Account

Status: local implementation candidate, 2026-08-30. Not deployed or enabled in
production. Resend sending-domain verification is a separate completed check,
not mailbox-delivery evidence. Authority: [identity/commerce contract](customer-identity-commerce-v1.md).

## Scope and ownership

Keep `/login`, `/account`, navigation, preferences, bookmarks and the API-key
compatibility bridge. Email is an independent identity, never a tenant label or
API credential. Verification creates an unsubscribed account; it cannot provision
data, create keys, associate existing tenants, create orders or collect payment.
SMS remains unavailable. Bookmarks remain browser-local, not account-synced.

The candidate account store is a dedicated Cloudflare D1 binding `IDENTITY_DB`.
`public-web/worker/identity-schema.sql` is for this store only; it must never run
against financial facts SQLite or any existing database without explicit review.
On 2026-08-30, following the owner's renewed go-ahead, the dedicated empty
`tradingdatas-identity-v1` resource was created and the schema initialized there.
Its candidate binding is recorded in `public-web/wrangler.jsonc`, with
`EMAIL_LOGIN_ENABLED="false"`. No Worker release or live binding was changed.
See the [provisioning checkpoint](../reports/2026-08-30-email-identity-provisioning.md)
for the exact resource, schema hash, empty-table readback and remaining gates.

## Control-plane routes

| Route | Result |
| --- | --- |
| `GET /api/account/auth-methods` | Configuration readiness: `email` boolean; `phone: false`. Not a delivery/health claim. |
| `POST /api/account/email/challenge` | `{email, locale}`; 202 with opaque `challenge_id`, `delivery: accepted`, `expires_in: 600`, `retry_after: 60` only after provider acceptance. |
| `POST /api/account/email/verify` | `{email, challenge_id, code}`; verify once, create/reuse identity and create independent session. |
| `GET /api/account/me` | With email cookie, verified identity and `not_subscribed`; without it preserve existing key bridge. |
| `DELETE /api/account/session` | With email cookie revoke server-side session, then clear both email and legacy cookies. |

An email projection contains `kind: email`, opaque `user_id`, verified `email`,
`email_verified: true`, `tenant_id: null`, `subscription_state: not_subscribed`,
`data_categories: []` and `session_expires_at`. It has no fake tier, quota, usage
or subscription expiry. Frontend validation rejects injected tenant/grant states.
The authenticated public data API stays `GET /v1/catalog` + `POST /v1/query`.

## Challenge, session and failure semantics

- Eight random digits, generated without modulo bias, valid for ten minutes.
  Only HMAC-SHA256 is stored for the code. Email normalization trims/lowercases
  conservative ASCII addresses; it does not collapse aliases, dots or `+` tags.
- Five well-formed verification attempts per challenge. A compare-and-set
  consume operation allows at most one concurrent success. Resend invalidates
  the previous challenge. Provider rejection/timeout leaves no accepted code.
- User creation and session creation use a D1 transaction batch, separate from
  challenge consumption. A failure after consumption fails closed; the user
  requests another code, not an automatic retry that creates two sessions.
- Session: 256 random bits; only SHA-256 hash at rest; eight-hour absolute expiry,
  no sliding extension. `td_identity_session` is HttpOnly, Secure, SameSite=Strict,
  Path=/api/account. Every read rechecks user disablement/session revocation.
- Exact same-origin mutations, JSON and 4 KiB streaming body limits, no redirects
  to alternative delivery hosts, eight-second provider timeout, no automatic
  email retry. Resend idempotency key is the challenge ID, never email/code.
- Provider acceptance is not inbox delivery. Known/new emails use the same
  challenge flow. Do not log addresses, codes, cookies, raw IPs or message bodies.
- A present email cookie never silently falls back to a legacy API-key cookie.
  Email sessions get 403 on usage/key operations and 409 on key login until
  sign-out. Verified email login clears the old key cookie.
- Identity-store outage returns 503, including sign-out; UI must not claim
  revocation. Invalid/expired/disabled sessions return 401. Legacy key-cookie
  logout retains its existing independent semantics.

## Abuse budget (candidate policy, not paid API limits)

Fixed windows in D1 survive Worker restarts. Email and IP bucket keys are HMACs;
only Cloudflare's overwritten `CF-Connecting-IP` is used at the Worker edge.
Missing client-IP evidence fails closed; do not publish a bypass origin that
trusts caller-supplied headers. Limits: global identity attempts 1000/10 minutes,
send requests 10/IP/hour, 5/email/hour and 100 globally/hour; email resend cooldown
60 seconds; verification 40/IP/10 minutes, plus five attempts per challenge.
Failed requests consume applicable budgets. Fixed-window boundaries can permit
two adjacent-window bursts; these are not rolling-window promises. A global
ceiling bounds cost but can also deny legitimate logins under abuse. Review
edge protection and volume policy before public enablement.

Expired challenge/session/rate rows are pruned in bounded batches of 100 per
send. Email addresses are PII in user/challenge rows; expiry prevents use but
opportunistic pruning is not a guaranteed deletion SLA. Before activation,
approve data retention/deletion, support ownership and a maintenance plan for
inactive periods. No timer or retention deletion job is deployed here.

## Configuration, release and rollback gates

New logins require all of `EMAIL_LOGIN_ENABLED="true"`, dedicated `IDENTITY_DB`,
server-secret `IDENTITY_PEPPER` (at least 32 characters, securely generated) and
least-privilege `RESEND_API_KEY`. Sender is fixed to
`TradingDatas <login@account.tradingdatas.com>`. The candidate Worker configuration
declares only the dedicated D1 binding and an explicit false enable flag; it
contains no secrets. The UI therefore stays unavailable after configuration-only
deployment, even if sender secrets are later added. Never put secrets in source,
URLs or chat.

Before activation: approve retention; review abuse budgets; provision approved
secrets privately; exact-head PR/CI review and the Datas PM merge gate;
staging sender verification to an explicitly approved recipient; check actual
inbox delivery, expiry/replay, session isolation, both legacy and email login,
logout and desktop/mobile rendering. Then separately authorize an exact-source
production deployment and verify runtime routes. Payments/SMS stay off.

Rollback new sign-ups first by setting the email enable flag false. Retain D1
binding and compatible session read/revoke code until existing sessions expire
or are revoked. Rolling back to code without email-session support would prevent
browser revocation of those sessions. Do not delete identity records, old keys,
data-plane storage, DNS or unrelated Resend domains as a deployment rollback.

## Local verification entry points

Implementation files (relative to `public-web/`):

- Worker: `worker/email-identity.js`, `worker/identity-schema.sql`; routing and
  legacy redirect rejection in `worker/index.js`.
- Existing UI: `src/LoginPage.jsx`, `src/App.jsx`, `src/accountSession.js`,
  `src/styles.css`; new in-place `src/EmailSignIn.jsx`, `src/EmailAccountPanel.jsx`.
- Verification: `tests/email-identity.test.mjs`, `tests/helpers/identity-db.mjs`,
  `tests/account-login.test.mjs`, `tests/account-session-lifecycle.test.mjs`,
  `tests/account-workspace.test.mjs`, `tests/sites-worker.test.mjs`.
- Packaging/review: `scripts/prepare-sites-build.mjs`,
  `scripts/preview-email-identity.mjs`, `scripts/check-email-runtime.mjs` and
  generated `dist/client` / `dist/server` artifacts. No lockfile change. The D1
  binding and disabled enable flag are candidate configuration, not a live Worker
  update. Documentation is synchronized in `public-web/README.md`,
  root `STATUS.md`, `docs/API.md`, `docs/OPERATIONS.md` and the parent identity
  contract. Current verification evidence and remaining gaps live in STATUS.

From `public-web`, Node 22.13+ (built-in `node:sqlite`) is required for tests and
the local identity harness. `npm run build` and `npm run test:sites` include
failure-path, race, isolation and packaging checks. The build copies the identity
module beside the existing Worker; test harnesses and schema are not served.

`node scripts/preview-email-identity.mjs` starts loopback-only port 5195 with an
in-memory identity store and synthetic `@example.com` messages. Open `/login`
and `/__test__/mail` to review; no external mail is sent. Restart clears fixtures.
An optional `node scripts/check-email-runtime.mjs /absolute/path/to/miniflare/dist/src/index.js`
runs the same Worker against local workerd/D1 with every outgoing request
intercepted. Neither harness is production evidence or a deployment command.

References: [D1 database API](https://developers.cloudflare.com/d1/worker-api/d1-database/),
[Resend email API](https://resend.com/docs/api-reference/emails/send-email).

## Login component review (2026-08-30)

Direction: retain the warm editorial Login/Account system. This is an in-place
email extension, not a new dashboard. Keep Inter/system English and PingFang/
Noto Chinese, existing heading/input/primary-button scales, surface shadows and
the shared reduced-motion rule. No new color or motion tokens.

Recovery actions now use the existing `--blue`, `--ink`, `--muted` and
`--radius-sm`: transparent surfaces, 13px/1.5 text, 44px minimum touch height,
8/16px spacing, wrapping, visible focus outline, hover underline and an explicit
disabled state without opacity washing out text. The primary verification
button retains priority. Inputs, account cards, tables and dialogs retain the
existing component contract; no parallel component system is added.

Component-level design-taste-pro assessment (manual, not a usability-study
result): hierarchy 18/20, typography 13/15, color 13/15, spacing 14/15,
feedback 9/10, accessibility 8/10, brand fit 9/10, responsive integrity 4/5:
**88/100**. Known risks: real-device software keyboard and screen-reader behavior
have not been tested; delivery remains synthetic in the local browser.
Next three checks: real-device keyboard/OTP autofill, screen-reader error/focus
announcements, and authorized real delivery plus return-to-preview acceptance.
