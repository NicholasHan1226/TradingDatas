# Payment flow preparation and integration

Current implementation authority: [Customer identity and commerce](customer-identity-commerce-v1.md).
The owner resumed subscription integration and payment testing on 2026-09-05.
This document describes the retained public selection flow and the eventual real
payment transitions. Merchant configuration and real settlement remain pending;
the isolated simulator is not payment-provider sandbox evidence. The fixed
catalog/query service continues independently.

## Implemented preparation

- Pricing -> `/pricing/preview?plan=basic&period=monthly` (six combinations).
- One price source: `public-web/src/pricing.js`. Monthly CNY 99 / 299 / 499;
  annual CNY 1,069.20 / 3,229.20 / 5,389.20. Same base data across tiers;
  only 200 / 600 / 1000 requests/minute differ. No daily/concurrency sales limits.
- Preview shows the entire period total, term, annual saving, shared data scope,
  no automatic debit, and an explicitly unavailable payment action.
- Public preview works before sign-in. Existing key holders can sign in and
  return to the canonical plan/term. The Login surface is the sole authority for
  which verified email or phone methods are currently available; this preview
  never collects contact details or presents fake verification codes.
- Selection is URL state only: non-sensitive plan/term, not a saved order or an
  authenticated purchase intent. Refresh, history and language changes retain it.
  Invalid, duplicate or extra parameters are rejected.
- Login `next` accepts `/account`, its known private overview/subscription/usage/keys/billing/security sections, or canonical preview selections. External
  redirects, API routes, arbitrary account parameters and payment flags are denied.
- Checking / signed out / unavailable / authenticated are distinct. All have
  payment disabled. Sign-in never changes subscription or grants.
- Account uses effective Portal access; Billing says unavailable, without a fake
  ledger or using token tier as proof of payment.
- Legacy `/pricing/beta` remains addressable but explicitly says applications
  are not open. It collects no input and links to Data and non-paying Pricing;
  it must not promise a waitlist, trial grant or an available application path.

The production preview creates no order, payment URL, invoice, refund or data
entitlement. Its development simulator separately supports test orders under the
current commerce contract. No frontend switch enables real checkout; no actual
payment-provider sandbox or production calls are implemented. Merchant onboarding
remains pending owner/provider configuration.

## Target customer flow — future server implementation

`Choose offer -> verified identity -> server-confirmed order -> payment ->
verified payment -> provisioning -> effective Account access`

Before a real order, disclose immutable offer version, currency, total, term,
scope, renewal behavior, applicable terms and refund/invoice policy. The server
derives tenant from verified membership. Price, grant, start/end dates and
settlement results are never browser authority.

| Situation | User-facing result | Required handling before live |
| --- | --- | --- |
| Preview, signed out or connected | Payment unavailable; no order | No ledger or grant writes |
| Identity pending / failed | Checking / retry sign-in | Preserve selection; no order creation |
| Offer changed | Review updated price/terms | Reconfirm; never charge stale client amount |
| Order creation uncertain / double click | Checking this order | Tenant-bound idempotency; read before retry |
| Awaiting payment | Pending payment, expiry visible | Provider-approved method and server expiry |
| Browser returns | Confirming payment | Return URL or screenshot is not evidence |
| Verified paid | Paid, activating | Signature, seller/app, order, amount/currency, trade state verified |
| Callback delayed/lost | Still confirming | Bounded provider-query reconciliation |
| Provisioning failed | Paid; activation delayed | Retry idempotent outbox; no duplicate charge or term |
| Entitlement readback succeeds | Active; authoritative expiry | Account/data API must reflect the same grants |
| Abandoned/expired/closed order | Not completed | Closing UI cannot close a provider trade |
| Late payment after local expiry | Reconciliation | Never discard verified funds or blindly grant stale offer |
| Manual renewal | Explicit new purchase | No automatic debit; agree term stacking before live |
| Upgrade/downgrade | Review terms | No implicit proration, refund or replacement assumption |
| Service expires | Access expired; renewal entry | Backend expiry, not browser clock, controls access |
| Refund requested/failed/confirmed | Separate refund status | Idempotent refund and explicit access-adjustment policy |
| Payment outage | Unavailable / safe retry | Preserve existing paid access and settled ledger |

Payment/order and subscription/access are separate projections. Never collapse
`paid + provisioning_failed` into unpaid, active or pay again. Unknown/malformed
server state means unable to confirm, never success. Production transitions remain unavailable. Isolated test-order behavior follows
the current account/commerce contract.

## Real payment implementation boundaries

- Identity store: verified credentials, explicit tenant membership, one-time
  challenges, revocable sessions, abuse protection and safe existing-key migration.
  No implicit account merge by typed contact or API-key label.
- Commerce store: versioned offers, tenant orders, attempts, verified events,
  subscription terms, provisioning outbox and audit/reconciliation logs. Separate
  from financial facts SQLite; no collector/registry side effects.
- Server provider adapter: server-only secrets, verification, request timeout,
  idempotency, query reconciliation and refunds. Never store raw keys in ledger.
- Tenant isolation: derive order/invoice ownership server-side. Anonymous
  previews have no customer IDs and cannot grant data.
- Deduplicate provider events and provision once transactionally; verify Account
  and data access without issuing duplicate keys or terms.
- Rollback: stop new checkout independently of callbacks/reconciliation and
  existing access. Never delete settled records or revoke old keys for UI rollback.

## Real collection activation checklist

1. Actual operating entity, website filing, merchant eligibility and dataset
   redistribution rights. Recheck requirements at resumption.
2. Signed terms, settlement currency, fees, single/day limits including the
   CNY 5,389.20 annual order. No payment splitting to evade limits.
3. Identity delivery providers/templates, durable identity/commerce storage and
   reviewed API contract. Existing access-key login is not signup.
4. Term timezone/month boundaries, renewal stacking, tier change, refund/access
   adjustment, tax/invoice and support policies. No guessed production defaults.
5. Sandbox: bad signature/merchant/amount/currency, replay, duplicate/out-of-order/
   late event, timeout, cross-tenant access, provision retry, exactly-once renewal
   and refund. Synthetic UI checks do not replace these integration tests.
6. Exact candidate CI, independent review, approved deploy, production readback
   and separately authorized bounded real payment before activation.

## Design and verification

Retain editorial canvas, Inter/PingFang and mono labels; existing ink/muted/line/
blue tokens, 4px spacing rhythm, 8/18px radii. One summary surface owns price
hierarchy; other sections use quiet rules, not equally weighted cards. No new
art, shadow, modal or token system. Mobile shows total/unavailability first.
Selection has visible focus/current states; disabled payment stays readable in
both themes. Existing 120ms selection feedback honors reduced motion. Global
search and Account layout are unchanged.

Verify with `cd public-web && npm run test:sites && npm run build`, then browser
checks of six combinations, invalid URLs, login return, identity states, refresh/
history, bilingual copy, mobile/tablet/desktop, themes and keyboard. Use the loopback synthetic harness for deterministic QA. Real customer and
provider verification follows the current commerce contract using the intended
recipient and approved configuration; do not substitute test fixtures for that evidence.
Record new results in a dated report and STATUS; the August preparation report is historical evidence.
