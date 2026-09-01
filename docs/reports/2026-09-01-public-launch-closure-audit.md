# Public launch-closure audit

Date: 2026-09-01 CST. Source candidate: `origin/main` at
`01d9806c9fd64ab1869d4941312185f06dc3d2db`. Scope: public-web source,
loopback verification and anonymous HTTPS readback. No server, collector, timer,
production database, payment provider or production secret was changed.

## Result

The public web candidate is locally buildable and its existing account, pricing,
research and evidence boundaries are explicit. It is **not** a completed account
or commerce launch:

- HTTPS `GET /api/account/auth-methods` returned
  `{"email":false,"phone":false}` during this audit. Email and phone sign-in
  are therefore not public features today.
- The public data-product pages intentionally show unverified collection evidence
  until a separately reviewed, authenticated receipt projection is available.
  The checked contract/config snapshot is not substituted for runtime health.
- Pricing remains a non-paying URL-state preview. It creates no order, charge,
  subscription or entitlement.

## Read-only configuration observation

At 23:05 CST on September 1, the Cloudflare dashboard showed that the live
`tradingdatas` Worker has the dedicated `IDENTITY_DB` binding and encrypted
`IDENTITY_PEPPER`, `RESEND_API_KEY`, and `SESSION_ENCRYPTION_KEY` secrets. The
separate Resend account showed `account.tradingdatas.com` as a verified,
send-enabled domain and a TradingDatas login key. The D1 Studio showed the six
expected account-only tables. Secret presence, domain verification, and schema
presence do not prove a successful delivery or login: both `EMAIL_LOGIN_ENABLED`
and `IDENTITY_RETENTION_ENABLED` remained `false`, as did the optional account
connection, library, and admin flags. No values, mail, D1 data, settings, or
Worker version were changed during this observation.

## Checks performed

- Baseline `npm run test:sites` and `npm run test:search` passed on Node
  26.0.0. After this documentation-only clarification, the focused research,
  public-evidence and account-workspace tests, `npm run audit:research` and
  `npm run build` passed.
- The local synthetic email identity harness reached the accepted-code UI using
  an `@example.com` fixture. It never contacted Resend or a real mailbox.
- At a 390 px local viewport, Data, Research and Pricing had no page-level
  horizontal overflow and no console errors. The public product pages retained
  the expected hierarchy and explicit unavailable-payment state.
- Anonymous HTTPS readback returned `200` for `/`, `/login` and
  `/api/account/auth-methods`; `/research` redirected to its canonical trailing
  slash path.

## Remaining activation gates

1. **Email account:** exact-head Worker upload, both email/retention flags,
   retention-job acceptance, recipient-authorized OTP delivery, session/replay/
   logout readback, and a separate role/tenant denial test. The configured D1
   binding, secret names, sender domain, template test and schema alone do not
   satisfy these gates.
2. **Data evidence:** a reviewed projection sourced from the existing
   authenticated catalog/receipt authority, with dataset identities and evidence
   time boundaries preserved. It must not create a provider call, public data
   route, or invented uptime metric.
3. **Commerce:** an independent server-side order and entitlement contract,
   merchant eligibility, payment verification/reconciliation, and Account/API
   entitlement readback. Client preview state remains non-authoritative.
4. **Research:** rerun the read-only audit and selected source checks before each
   editorial batch, then verify the exact deployed rendering separately.

## Rollback boundary

No activation occurred in this audit. A later activation rollback must disable
new entry flags first while preserving account-session revocation and any
required retention work. It must never delete data-plane facts, API keys,
financial SQLite, payment records or unrelated Cloudflare resources.
