# Payment preparation review — 2026-08-30

## Scope and authority

Owner requested payment closure be deferred while preparing the flow. This
candidate combines login head `fcb59eb` (PR #386) and price-display head `e86652d`
(PR #387) in the isolated `codex/checkout-flow-preparation-v1` worktree. Neither
original branch was changed. This integration is not PM approval, merged main,
CI acceptance, deployment, verified identity delivery or live payment.

## Changes

- `PurchasePreview.jsx`, `purchasePreview.js`, `purchasePreview.css`: public
  non-paying selection/price summary, fail-closed parsing, identity-state display.
- App/Login wiring: canonical URL plan/period, strict login return, refresh and
  browser-history support, existing Account subscription/billing continuation.
- Existing `pricing.js` remains the only display price source. All three tiers
  share base scope; alternatives are excluded; manual renewal/no auto debit.
- Synthetic QA server optionally accepts `TRADINGDATAS_QA_PORT`; still loopback,
  no production calls. Used port 5194 to preserve the other review server.
- Product, public surface map, design contract and module guidance updated with
  the preview boundary. Personal-Alipay record now reflects the logged-in form,
  missing filing and explicit owner pause. Lifecycle/resumption entry:
  [payment flow contract](../design/payment-flow-preparation-v1.md).

## Fresh verification

- Test-first: purchase-preview suite initially failed because the module did not
  exist; after implementation all six new tests passed.
- `npm run test:sites`: **64 passed, 0 failed**; includes existing session, account,
  search, route and Worker tests plus approved prices and purchase preview.
- Six selection combinations use exact minor-unit totals; duplicated/extra/invalid
  parameters and external login destinations are rejected. No selection can
  enable payment, create an order or change access.
- Unimplemented checkout/order/notification writes remain 404/503 fail-closed.
- `npm run build` passes. Compiled client and Sites worker outputs regenerated.
- `node --check scripts/login-qa-server.mjs` and `git diff --check` pass.
- Module-rule edit is file-verified; discovery in a separate fresh Codex session
  has not been tested. No global rule or memory files were changed.
- Browser: Pricing preview entry and return retain Flagship annual selection;
  reload preserves CNY 5,389.20; back/forward restores previous selections.
- Synthetic successful key login returns to Professional annual (CNY 3,229.20).
  Account still shows the original synthetic Basic/200-per-minute grant, not
  the selected Professional offer. No real credentials were used.
- Invalid-key attempt shows the error and preserves the preview return link.
  Identity outage shows retry/unknown identity, not signed out or payment success.
  Checking and signed-out states were also inspected in the browser.
- Billing explicitly says unavailable and no simulated records. No zero-order
  count is presented as a real ledger result.
- English dark and Chinese light rendering inspected. Mobile (320/390), tablet
  (768) and desktop (1280) checked; document width equalled viewport width at
  each. Mobile puts summary/total before detailed choices. Temporary viewport
  override reset after review.
- Native links receive focus, but the in-app browser's automated Enter did not
  dispatch navigation. Pointer navigation and history passed; native keyboard
  activation and full screen-reader traversal remain unverified. No duplicate
  keyboard handler was added to native links as an automation workaround.

## Design review

Direction: compatible editorial extension, not a redesign. Existing color,
typography, spacing and radius tokens are reused without new design tokens.
One light/dark summary surface prioritizes total; numbered quiet sections clarify
plan, period and account; paused state is explicit and not a marketing CTA.

Manual score (not automated accessibility certification): hierarchy 18/20;
typography 13/15; color semantics 14/15; spacing 14/15; feedback 9/10;
accessibility 7/10; brand fit 9/10; responsive integrity 5/5. **Total 89/100**.
Observable improvements: exact annual total has one focal point, login retains
selection, and preview is visibly separate from current paid access.

Next three validation priorities: native keyboard/screen-reader check; verified
phone/email identity and tenant binding; sandbox payment/activation/reconciliation
only after the resumption prerequisites and authorization are available.

## Not implemented / not authorized by this preparation

- Merchant application/signature, ICP filing, hosting migration, live secrets.
- Real order store, provider checkout, signature validation handler, provisioning,
  renewal calculation, refunds, invoices or real payment testing.
- Phone/email sender accounts, verified signup or identity migration.
- Upstream data-rights approval, settlement/limits, final term/refund/tax policies.
- Main merge, GitHub push/PR or production deployment of this new candidate.

The paused flow cannot be enabled by editing a client flag. Server architecture,
contracts, tests and separate activation approval are still required. Existing
production service, keys, collectors and financial-facts SQLite were untouched.

Rollback: discard/revert this local candidate or the preview integration patch;
there is no payment/order state to migrate or undo. Preserve the independent
login and pricing candidates and all existing credentials.
