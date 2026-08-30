# Personal Alipay checkout — implementation boundary

Decision: owner accepted active period purchase and manual renewal on 2026-08-30.
Status: design contract only; no merchant contract, payment request, callback,
identity migration or entitlement activation is implemented by this document.

## Product contract

- Keep the existing TradingDatas Account. Phone and email are independently
  verified sign-in methods for one identity, not separate workspaces. A typed
  contact or possession of a data key is not sufficient to silently bind an
  existing customer identity. Sender accounts/templates, identity persistence,
  one-time challenge verification and revocable sessions remain prerequisites.
- Sell three base-data tiers: basic 200/min, standard 600/min, flagship 1000/min.
  Same base data scope, no commercial daily quota or concurrency ceiling.
- Owner-approved monthly amounts: 99 / 299 / 499. Annual payment is 90% of
  twelve monthly payments: 1,069.20 / 3,229.20 / 5,389.20. Domestic-first display
  assumes CNY; settlement currency and invoice/tax treatment must be confirmed.
- One active purchase grants the explicitly stated term; no automatic debit or
  subscription mandate, and no hidden alternative-data trial conversion.
- Alternative data remains a separate later purchase, outside base-plan checkout.

## Official evidence checked 2026-08-30

1. [AI web-app collection](https://aipay.alipay.com/products/ai-web-app) explicitly
   supports personal collection scenarios and desktop/mobile web.
2. [Integration guide](https://aipay.alipay.com/docs/ai-web-app-payment-qianyi/ai-web-app-payment-integration-guide.html)
   (page updated 2026-08-28) requires authoritative notification or query results,
   verification of notification signatures and matching app/order/amount. A
   browser return is not payment evidence.
3. [Onboarding](https://aipay.alipay.com/open-flow/products?product=web) presents
   an Alipay QR login before account-specific eligibility/contract details. This
   task stopped there; no agreement was accepted and no real charge was made.

Do not infer financial-data resale eligibility from a general personal-account
feature. Actual business category, supporting documents, seller identity,
settlement, fees, per-transaction and daily limits await account-specific review.
In particular, validate the 5,389.20 annual order; do not split payments to evade
a limit or import a limit from another Alipay product's documentation.

## Smallest safe checkout flow

1. Verified user/tenant selects a server-owned versioned offer and term. Client
   price, tier, tenant, expiry or grants are never trusted input.
2. Backend records a pending order in a separate account/commerce store and
   requests the officially permitted web payment method. It uses server-only
   signing material and unique merchant order numbers.
3. Verify signatures and match app/seller, order, amount and currency as
   applicable to the contracted API. Confirm paid trade state; ignore the browser
   success page as authority. Reconcile missing or delayed callbacks with query.
4. Transactionally deduplicate provider events; only verified payment can queue
   idempotent entitlement provisioning. `Paid, activating` is distinct from
   `Active`. Retry failures without issuing duplicate terms or extra keys.
5. Account reads actual grants and expiry. A returning customer actively pays
   to renew; agree term-boundary/timezone, upgrade and refund rules before coding.
   Never grant privileges just because registration succeeded or a QR was shown.
6. Refunds use the approved provider route with idempotent refund identifiers,
   reconciliation and an explicit access policy. No ad-hoc personal transfer or
   screenshot-based automatic activation.

## Before activation

- Owner logs into official onboarding and reviews eligibility/fees/limits and
  legal terms; signing and real-payment approval remain owner actions.
- Supply merchant app configuration and sandbox credentials through approved
  secrets management, never chat/source/screenshots; no global skill install
  or external account creation is implied by this design.
- Confirm phone/email delivery accounts, identity ownership, refund/invoice,
  term/upgrade rules and permissible redistribution of the sellable dataset set.
- Sandbox tests: invalid signatures, amount mismatch, duplicate/out-of-order
  events, abandoned/closed orders, delayed confirmation, provision failure,
  renewal exactly once, refund and cross-tenant access denial.
- Approved exact-main release, fresh production readback and separately approved
  minimal real payment are required before marking checkout live.

The public data plane stays read-only `GET /v1/catalog` + `POST /v1/query`.
Do not put identity/orders/payment ledgers in financial-facts SQLite or alter
collectors, providers, tokens or production services to bypass these gates.
