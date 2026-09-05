# Customer identity and commerce

Authority: [Product](../PRODUCT.md), [Account convergence](account-admin-convergence-v1.md),
[API](../API.md). This document owns the account/commerce implementation boundary;
STATUS owns dated release and real customer evidence. Last contract review: 2026-09-05.

## Current scope

The owner resumed subscription integration and payment testing on 2026-09-05.
Independent email identity, session revocation and explicit existing-key connection
already exist. They do not depend on payment activation. The current release work
adds a server-read commerce surface and a durable **isolated simulator**, not a
verified payment-provider sandbox or a production merchant integration.

Production checkout remains unavailable until actual merchant configuration,
settlement terms and provider integration are supplied and verified. These missing
inputs do not stop frontend/backend development, existing authenticated data
service or independent dataset onboarding. Source quality is handled per dataset
under [Operations](../OPERATIONS.md#接入供数与质量的边界), not a commerce-wide gate.

## Identity, access and purchase are independent

- Keep one `/account` workspace and the existing `/login` entry. Verified email
  sessions use `IDENTITY_DB`; Resend supplies email delivery. SMS remains deferred.
- `/api/account/me.identity` is identity only: `tenant_id: null`,
  `subscription_state: not_subscribed`, no implicit categories. This compatibility
  field does not describe the separate commerce ledger.
- Explicit existing-key connection produces `data_access`. Portal remains the
  authority for effective tier, expiry, categories, rate limits, usage and keys.
  Neither an email address nor a paid order can substitute for that readback.
- Commerce records are owned by the verified session user, never a browser-sent
  user, tenant, price, date or role. Legacy key-only sessions have no inferred
  billing identity. A data or commerce outage does not silently end email login.
- Keep independent admin/library feature switches. Registration cannot create
  admin authority, customer grants or cloud bookmark availability.
- Financial data requests remain Bearer-authenticated `GET /v1/catalog` and
  `POST /v1/query`. No commerce table or credential enters financial facts SQLite.

## Offers and terms

The only price source is `public-web/src/pricing.js`. Basic/Professional/Flagship
map to `basic`/`standard`/`flagship`, at 200/600/1000 requests per minute. Monthly
display prices are CNY 99/299/499; annual totals are CNY 1069.20/3229.20/5389.20.
There is no commercial daily quota or concurrency limit, and no automatic debit.
These are confirmed display choices, not a signed settlement contract.

Server offers contain an immutable version, tier, period, currency, integer minor
amount and request rate. The isolated simulator labels every offer, order and
subscription `environment: sandbox`. Its `sandbox-fixed-days-v1` terms exist only
for deterministic tests and must never become production renewal defaults.
Alternative data, trials, upgrades, refunds and automatic renewal are not silently
added to this base-plan slice.

## Account commerce API

All routes use the existing verified email session and expected `X-TD-Identity`.
Writes retain exact same-origin protection. Account switching clears prior data
and discards late responses. Responses are private and `no-store`.

| Route | Contract |
| --- | --- |
| `GET /api/account/commerce` | `{mode, checkout_available, subscription, orders, offers}`; bounded recent order list |
| `GET /api/account/offers` | Server offers with mode and checkout availability |
| `POST /api/account/orders` | Only `{offer_id, offer_version}` and `Idempotency-Key`; returns the owned order |
| `GET /api/account/orders/:id` | Owned order only; another user's order and unknown ID both return 404 |

`mode: unavailable` with empty projections means no configured commerce ledger,
not proof that a customer has never paid elsewhere. A storage error is a failed
read with a retry state, not an empty history. Only the isolated test binding can
currently enable checkout. Production configuration cannot create orders, payment
events or grants through these routes. The UI must not display a working payment
button based on local state or a URL parameter.

The subscription projection contains ID, tier, period, server start/expiry, state,
environment and terms version. Orders include immutable offer identity/amount,
creation time, payment state and provisioning state. Payment `pending` versus
`verified_paid` is separate from provisioning `not_provisioned`, `pending`,
`active` or `failed`. Paid plus failed provisioning means **payment confirmed,
activation delayed**, never unpaid, pay again or actual production access.

## Durable isolated simulator

The test commerce store is separate from identity and financial data. Four tables
hold orders, deduplicated events, subscriptions and provisioning attempts. No
identity cascade can delete purchase records, and no commerce foreign key can
block existing identity retention. There is no production commerce migration in
this slice. Production billing retention/anonymization must be decided before
binding a real store; copying the sandbox schema into IDENTITY_DB is unsupported.

A user/idempotency-key pair creates one immutable order; reusing that key with a
different offer conflicts. Verified events must match the order, merchant,
amount and currency before recording payment. Event replay and provisioning
retry cannot duplicate an order's term. A browser redirect, `paid=true`, screenshot
or client assertion never changes payment state. Simulator verification is an
injected test dependency, not an unauthenticated public callback or success button.

Payment acknowledgement and its provisioning work are recorded atomically.
Provisioning only touches isolated test grants; it does not invoke production
Portal key creation. A real subscription adapter must provide idempotent durable
entitlement writes and revalidation of already-issued keys on renewal before it
can replace this test implementation.

## Remaining real-service inputs

1. Intended test recipient and an ordinary customer's existing data access for
   delivered OTP → sign-in → connection → catalog/query → usage readback.
2. Actual payment provider/merchant, approved settlement currency and sandbox
   credential location (never secrets in chat), then real provider sandbox tests.
3. Production term timezone/month boundaries, renewal stacking/tier-change policy,
   refund/tax/support treatment and approved sellable dataset scope.
4. Production commerce retention and entitlement provisioning/renewal adapter.
5. A bounded real-payment test only after those facts are established and its
   amount/merchant/rollback are authorized. Simulator tests are not that evidence.

No merchant onboarding submission, contract acceptance, service purchase or live
charge follows merely from preparing this code. Keep these pending inputs visible
without blocking the work that does not require them.

## Verification and rollback

Use the existing public-web test/build entry points. Verify ownership, identity
switches, stale offers, unexpected client fields, idempotent/concurrent creation,
wrong/forged payment events, duplicate callbacks, provisioning failure/retry and
durable readback after reopening the test store. Inspect bilingual Account and
preview pages at desktop/tablet/mobile sizes with empty, unavailable and pending
states. Real email delivery, authenticated API success and provider sandbox
settlement each require separate real evidence.

Disable new checkout independently from event reconciliation and existing access.
Never erase settled records, reset terms, delete existing keys or disable working
data access as a payment rollback. Exact source, CI, public release, financial
runtime and actual user/provider outcomes are reported separately in STATUS.
