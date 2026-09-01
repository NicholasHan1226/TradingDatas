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

The owner-designated email is also intended to be the administrator identity.
This candidate does not grant roles or bridge admin sessions. Keep the same user
identity and public Account; the subsequent [owner access contract](account-admin-convergence-v1.md#owner-identity-and-two-workspaces)
requires explicit server authorization after verification, not an email comparison
inside this login handler. A test delivery alone must not activate that role.

Outbound sign-in messages use the shared [transactional email template system](transactional-email-system-v1.md)
with authored Chinese/English HTML and plain text; expiry comes from the challenge
policy. All future external messages, including delivery tests, require a reviewed
template. The shared rendering layer does not send mail or alter identity authority.
Email language is resolved from the initiating device/browser's primary language
on each send and resend, not the manual website language setting. Chinese variants
map to `zh`; every other or missing language maps to `en`. This presentation hint
does not influence email verification, account identity, roles or data grants.

The candidate account store is a dedicated Cloudflare D1 binding `IDENTITY_DB`.
`public-web/worker/identity-schema.sql` is for this store only; it must never run
against financial facts SQLite or any existing database without explicit review.
On 2026-08-30, following the owner's renewed go-ahead, the dedicated empty
`tradingdatas-identity-v1` resource was created and the schema initialized there.
Its candidate binding is recorded in `public-web/wrangler.jsonc`, with
`EMAIL_LOGIN_ENABLED="false"`. No Worker release or live binding was changed.
See the [provisioning checkpoint](../reports/2026-08-30-email-identity-provisioning.md)
for the exact resource, schema hash, empty-table readback and remaining gates.
The [August 31 preparation](../reports/2026-08-31-identity-private-provisioning.md)
adds the account-only deletion schema and privately stages sender/pepper secrets
in an undeployed old-code Worker version. It does not activate identity or change
the live service; a later exact-source release must verify secret preservation.

## Control-plane routes

| Route | Result |
| --- | --- |
| `GET /api/account/auth-methods` | Configuration readiness: `email` boolean; `phone: false`. Not a delivery/health claim. |
| `POST /api/account/email/challenge` | `{email, locale}`; 202 with opaque `challenge_id`, `delivery: accepted`, `expires_in: 600`, `retry_after: 60` only after provider acceptance. |
| `POST /api/account/email/verify` | `{email, challenge_id, code}`; verify once, create/reuse identity and create independent session. |
| `GET /api/account/me` | With email cookie, verified identity and `not_subscribed`; without it preserve existing key bridge. |
| `DELETE /api/account/session` | With email cookie, matching `X-TD-Identity`, revoke the D1 session then clear both cookies. Mismatch is `409 identity_changed`; D1 outage is `503`, never a successful revoke. |
| `POST /api/account/profile/deletion` | Current email identity only; `{confirmation: "DELETE"}`, same origin, verification within ten minutes. Atomically accept explicit deletion, disable identity and revoke all email sessions; 202 is acceptance, not completed purge. |

An email projection contains `kind: email`, opaque `user_id`, verified `email`,
`email_verified: true`, `tenant_id: null`, `subscription_state: not_subscribed`,
`data_categories: []`, `session_expires_at` and `deletion_available` (the retention
feature flag, not scheduler health). It has no fake tier, quota, usage
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
- Before each identity readback, including returning to a visible tab, clear all
  derived account projections and any one-time raw key, advance the request epoch
  and abort the previous read. Another tab can change the shared cookie; an old
  key or usage view must never be adopted with the newly returned identity.
  A one-time key display therefore does not survive foreground revalidation,
  even when the returned identity is unchanged. This is not cross-tab revocation
  broadcasting; in-flight-operation refresh guards remain in place.

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

Expired challenge/session/rate rows are also pruned opportunistically per send.
On 2026-08-30 the owner approved active-store maximum retention: expired OTP
records within 24 hours, invalid sessions within seven days, and profiles within
30 days after an explicit deletion request. The separately gated hourly job
targets earlier cleanup and preserves profiles without requests. See
[Account retention and deletion v1](identity-retention-v1.md) for the additive
schema, bounds, failure/rollback controls and all-copies limitation. This local
implementation is not proof of a live scheduler or a deletion SLA.

## Configuration, release and rollback gates

New logins require all of `EMAIL_LOGIN_ENABLED="true"`,
`IDENTITY_RETENTION_ENABLED="true"`, dedicated `IDENTITY_DB`, server-secret
`IDENTITY_PEPPER` (at least 32 characters, securely generated) and least-privilege
`RESEND_API_KEY`. This shared runtime readiness gate prevents new identity data
from being collected while scheduled retention is intentionally disabled; it
does not prove the migration, cron, latest maintenance receipt or backlog health.
Sender is fixed to
`TradingDatas <login@account.tradingdatas.com>`. The candidate Worker configuration
declares the dedicated D1 binding and explicit false email/retention flags; it
contains no secrets. The UI therefore stays unavailable after configuration-only
deployment, even if sender secrets are later added. Never put secrets in source,
URLs or chat.

Before activation: apply and verify the approved retention policy and additive
schema/scheduler; review abuse budgets; provision approved
secrets privately; exact-head PR/CI review and the Datas PM merge gate;
staging sender verification to an explicitly approved recipient; check actual
inbox delivery, expiry/replay, session isolation, both legacy and email login,
logout and desktop/mobile rendering. Then separately authorize an exact-source
production deployment and verify runtime routes. Payments/SMS stay off.

The shared attempt budget and the applicable per-IP budget are admitted in one
atomic D1 statement. If either limit is full, neither counter changes and a full
shared budget cannot create a new attacker-controlled IP bucket. Malformed
requests and failed OTP/provider outcomes that pass this coupled admission
continue to consume the applicable budgets.

Rollback new sign-ups first by setting the email enable flag false. Retain D1
binding and compatible session read/revoke code until existing sessions expire
or are revoked. Rolling back to code without email-session support would prevent
browser revocation of those sessions. Do not delete identity records, old keys,
data-plane storage, DNS or unrelated Resend domains as a deployment rollback.

## Local verification entry points

Implementation files (relative to `public-web/`):

- Worker: `worker/email-identity.js`, `worker/identity-schema.sql`; routing and
  legacy redirect rejection in `worker/index.js`.
- Account retention: `worker/identity-retention.js`, additive
  `worker/identity-retention-schema.sql`, and the gated scheduled handler.
- Existing UI: `src/LoginPage.jsx`, `src/App.jsx`, `src/accountSession.js`,
  `src/styles.css`; new in-place `src/EmailSignIn.jsx`, `src/EmailAccountPanel.jsx`.
- Verification: `tests/email-identity.test.mjs`, `tests/helpers/identity-db.mjs`,
  `tests/identity-retention.test.mjs`, `tests/account-deletion.test.mjs`,
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
The preview injects `CF-Connecting-IP`; Vite `npm run dev` does not serve these
routes. An optional `node scripts/check-email-runtime.mjs /absolute/path/to/miniflare/dist/src/index.js`
runs the same Worker against local workerd/D1 with every outgoing request
intercepted. Miniflare is not a repository dependency. Neither harness is
production evidence or a deployment command.

JSON `error` codes, cookie names and request examples live in
[API.md](../API.md#independent-email-identity-candidate). Operator distinction
between key-bridge `identity_gateway_unavailable` and email
`email_login_unavailable` / `identity_unavailable` is in
[OPERATIONS.md](../OPERATIONS.md#identity-troubleshooting-not-production-enablement).
The Login UI collapses most 5xx into generic send/verify copy; read the JSON.

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
