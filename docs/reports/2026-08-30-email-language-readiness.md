# Email language and launch readiness · 2026-08-30

Scope: public-web email candidate on `codex/email-identity-v1`, PR #397.
Base integration: `7531e3615e0decbd84a4a30f51c6f613ff76080f`; no production rollout.
This record supersedes neither data-plane status nor the PM merge gate.

## System language

The owner requires Chinese/English emails to follow the recipient's system language.
`src/systemEmailLocale.js` reads the primary browser language (falling back to the
first `navigator.languages` entry if needed). Chinese variants map to `zh`; other
or unavailable languages map to `en`. Browsers may override the operating-system
preference; the website cannot inspect an unrestricted OS setting. Website language
selection stays independent. `EmailSignIn` resolves the value on every send/resend.

Tests cover Simplified/Traditional/regional Chinese, English, other languages,
missing language and primary-language precedence. Sender integration checks the
same helper through the real identity handler, with synthetic delivery, including
language changes on resend. Both HTML and authored plain text use the same template.
No background subscription/security email is implemented; such events must first
retain a verified recipient preference and define their own reviewed template.

## Authorized branded delivery

Following the owner's instruction to execute the next checks, one `delivery-test-v1`
Chinese HTML + plain-text email was sent to the privately confirmed owner recipient.
The actual local OS preference was `zh-Hans-CN`; no recipient literal or message body
is stored in this report. Sender: `login@account.tradingdatas.com` (the connector
accepts a bare mailbox; the production template sender retains its approved display name).

- Resend ID: `ee858c3a-20c1-4ab0-90ed-94e304176a45`.
- Provider creation: `2026-08-30T14:22:59.804Z`.
- Fresh Get Email readback: `delivered`, Chinese subject, Chinese HTML and text.
- This proves provider-reported delivery only. Inbox/spam placement, user receipt,
  QQ rendering, real OTP verification and administrator authority are not implied.
- No second English message was sent; English remains covered by local tests/previews.

## Remaining sequence and stop lines

| Item | Current evidence | What remains |
| --- | --- | --- |
| Login readiness | Candidate code, dedicated empty account D1, disabled flag; local tests/build/workerd checks | Exact-head CI, security review, PM merge; approved retention and privately provisioned secrets |
| Branded OTP acceptance | Brand delivery test reported delivered; synthetic OTP flow verified locally | Real staged OTP through the deployed identity handler, user entry, expiry/replay/logout readback |
| Same owner identity / Admin | Existing public Account retained; explicit role contract documented | Reviewed server-owned stable-user role, privileged-request boundary, provisioning, audit and readback |
| Identity / subscription / keys | Existing key-authenticated Account reads real portal facts; email identity truthfully unsubscribed | Explicit verified user-to-tenant binding and scoped backend credential contract; never automatic email/label matching |

Proposed retention for owner decision, **not approved or deployed**: expired OTP
records cleared within 24 hours; invalid sessions within 7 days; account profile
retained until deletion request, then deleted within 30 days. Define how revocation,
backups and abuse/audit records interact before offering a deletion SLA. Existing
bounded opportunistic cleanup is not that SLA; no production deletion job was added.

Do not provision or enable the live login merely because the delivery test succeeded.
Do not add an admin link that disguises a second login as shared identity. Do not
attach old API credentials to a typed email or grant a paid plan from client state.
Payments and SMS remain off. Data collection, production users and roles are untouched.

Verification entry points: `cd public-web && npm run build && npm run test:sites`;
`node scripts/check-email-runtime.mjs /absolute/path/to/miniflare/dist/src/index.js`.
Fresh local result: build passed; **95/95 tests passed**; local workerd + isolated
D1 passed one-use verification, account isolation, revocation and legacy regression.
The current browser form reached the accepted-code state and its synthetic outbox
contained the English branded HTML + text. A previous preview process still had
the old module in memory; it was not used as current-version evidence. New review
uses the isolated 5197 process below. No production OTP was sent by these checks.
Local preview: `TD_IDENTITY_PREVIEW_PORT=5197 node scripts/preview-email-identity.mjs`,
example.com-only mock delivery, memory-only DB; not a real account/email test.
Rollback: revert this language patch and regenerate client artifacts; no schema,
secret, collection-service or production-data rollback is involved.
