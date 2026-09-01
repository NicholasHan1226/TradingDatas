# Public evidence and Agent readiness — candidate acceptance

Verified 2026-08-31, Asia/Shanghai. Follow-on branch
`codex/public-evidence-readiness-v1`, based on account candidate `a5a9c692`
(PR #408). This record is not production activation or customer acceptance.

## Delivered scope

- Preserve existing Account, identity isolation and administrator authorization.
  No second customer dashboard, new schema, secrets, roles or payment/SMS changes.
- Remove authored 99.98% stability, invented daily-product receipt/coverage and
  synthetic 90-day history claims. Keep the evidence area, explicitly unverified
  on this page; this does not mean collection never started elsewhere.
- Label synthetic rows and receipt illustrations locally. Product definitions
  and historical source snapshots are not live API coverage counts.
- Query copy is a non-executable catalog-derived template, not a product slug or
  guessed schema. Copy success/failure and late completions are handled.
- Five named/generic Agent variants in Chinese and English derive from the
  canonical integration document. Missing public origin remains a draft. HTTP
  tool instructions do not assert a deployed MCP server or a working connection.
- Dialog retains keyboard focus, handles Escape/return focus and suppresses the
  background search shortcut. No prompt contains credentials or sends requests.

## Verification

- Public-web tests: **143/143 passed**, including 16 new evidence/prompt tests.
- Production build passed. Agent dialog is lazy-loaded; the main bundle remains
  approximately 500.28 kB minified and retains Vite's 500 kB advisory.
- Local real workerd + D1 regression passed for email identity, isolated library,
  encrypted connection, admin rejection, revocation/purge and redirect rejection.
  This uses isolated fixtures; no real email or remote database write.
- Browser: desktop English/light and Chinese/dark, 390px nested viewport, Agent
  selection/copy state, Tab wrap, Escape/return focus and Cmd+K containment.
  Mobile review used the local synthetic Account harness, not a customer's phone.
  Clipboard failure is code-reviewed; no browser fault injection was performed.
- Independent read-only review found an API-contract mismatch in prompt wording.
  Corrected to `queryability.queryable === true`, otherwise report
  `queryability.reasons`; all variants have regression assertions. No remaining
  confirmed P0/P1 in the frozen frontend correction scope.

## Bounded real internal data readback

Existing read-only authentication was used in-memory on the canonical production
host; no keys, service changes or provider collection were created. The A-share
release observed was `ddccda103b904ba179a7c76cf722d7cf561b7fe6`.

1. Authenticated catalog selected `cn.equity.daily`, schema major **2**, with
   `queryability.queryable=true`. Selectable volume is `vol`, not `volume`.
2. A new catalog read supplied dataset/schema and the available trade date. A
   query selecting `ts_code`, `trade_date`, `close`, with an equality date filter
   and `limit=1`, returned HTTP 200 and **one row**.
3. Metadata reported success, not degraded, fresh, valid quality and complete
   SQLite-receipt lineage; data-through was 2026-08-31. No market row payload,
   credential or raw receipt artifact is committed here.

This verifies one existing internal consumer path only. It does not establish
public routing, email-linked customer entitlement, continuous cadence, complete
history, PIT, redistribution rights or latest-main deployment. PR #407's newer
row-receipt validation was not the effective release during this probe. Other
data-plane maintenance belongs to its separate task and was not modified.

## Unfinished gates and next action

- Public `https://api.tradingdatas.com/v1/catalog` did not resolve during this
  check; `https://tradingdatas.com/api/account/auth-methods` returned **404**.
  Neither is represented as a functioning public onboarding path.
- PR #408 remains an unpublished dependency. Its exact-head four CI shards were
  green when checked, but it was Draft with no `pm-merge` approval. CI is not PM
  acceptance. The new candidate also requires its own exact-head CI.
- No production deployment, flags, DNS, secret provisioning, remote D1 migration,
  customer role change, real OTP send, payment or SMS occurred in this turn.
- After PM acceptance of the integrated candidate: separately validate approved
  deployment/configuration and rollback; then execute real OTP → existing data
  access → subscription/expiry → bookmarks → logout and admin-denial checks.
  Public Agent catalog/query acceptance follows only after its origin and
  authentication are actually available.
- Authenticated collection-history projection remains future work; do not restore
  illustrative percentages as a substitute for receipts.

Contract: [public evidence readiness](../design/public-evidence-readiness-v1.md).
Account predecessor: [account continuity](2026-08-31-account-continuity.md).
