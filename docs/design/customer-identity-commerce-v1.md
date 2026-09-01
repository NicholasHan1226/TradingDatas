# Customer identity and commerce — implementation contract

Status: Git-merged display and identity-method contract (PR #387), plus later
gated email-identity and non-paying purchase-preview work on main. Confirmed
prices, dual identity methods and Resend selection are product decisions, not
runtime payment authority or permission to collect charges. Product authority:
[Product](../PRODUCT.md); current account design:
[Account convergence](account-admin-convergence-v1.md); current API:
[API contract](../API.md).

## Confirmed boundaries

The owner paused payment activation on 2026-08-30; continue non-paying flow
preparation only. Active period purchase with manual renewal/no automatic debit
is confirmed. See [implementation and resumption gates](payment-flow-preparation-v1.md).

- Keep one customer workspace at `/account` and the existing visual language.
  `/login` becomes the identity entry without introducing another dashboard.
- Public data requests remain authenticated `GET /v1/catalog` and
  `POST /v1/query`. New identity/commerce operations belong to the account
  control plane, never provider-specific public data routes.
- Basic maps to `basic` (200 requests/minute), Professional to `standard` (600),
  Flagship to `flagship` (1000). No commercial daily quota or concurrency tier.
- Website login must eventually be independent of Agent/API credentials.
  Current access-key-to-cookie exchange is only a compatibility bridge.
- Owner confirmed both mobile-phone and email login/registration on 2026-08-30.
  The target is one account supporting separately verified credentials, not two
  separate customer workspaces. Linking requires an authenticated account plus
  verification of the new credential; never merge accounts by typed contact.
- Owner selected the existing Resend account for email on 2026-08-30; SMS has no
  provider yet. Deliver email first without requiring SMS configuration. The
  dedicated sending domain is `account.tradingdatas.com`, with intended sender
  `TradingDatas <login@account.tradingdatas.com>`. Domain setup is not an enabled
  login flow or proof of delivery. See [email preparation](../OPERATIONS.md#resend-account-email-preparation).
- Owner confirmed monthly prices of 99 / 299 / 499, and annual payment at 10%
  off twelve monthly prices. Annual totals are 1,069.20 / 3,229.20 / 5,389.20;
  monthly equivalents are 89.10 / 269.10 / 449.10. Public display assumes CNY
  for the domestic-first product; confirm settlement currency before activation.
  These are price-display decisions, not evidence of live checkout or renewal.
- An unpurchased or unpaid order never grants data. Category authorization,
  upstream redistribution permission and runtime availability remain separate.
- Alternative-data selling is not part of the initial base-plan checkout.
  Do not create a hidden add-on or a silent trial-to-paid conversion.
- Identity, orders and payment records do not belong in financial facts SQLite.
  Do not migrate the data plane or repurpose its service credentials.
- The owner-designated email identity must access both public Account and Admin,
  using explicit server-side role authorization after verification, not separate
  accounts or client email matching. This is a confirmed target, not an existing
  admin session bridge; see the [owner workspace contract](account-admin-convergence-v1.md#owner-identity-and-two-workspaces).

## Existing implementation and gaps

| Capability | Existing surface | Work needed |
| --- | --- | --- |
| Browser access | Encrypted eight-hour account cookie wrapping an access key | Stable user identity and independently revocable sessions |
| Account access | Tenant-scoped Portal projection and API key management | Verified user-to-tenant binding; no email-string tenant matching |
| Price display | `public-web/src/pricing.js` plus `/pricing` and `/pricing/preview` | Server-owned offer versions; settlement currency confirmation |
| Commercial limits | Server-enforced basic/standard/flagship minute limits | Approved sellable offers and subscription entitlement provisioning |
| Payment | Non-paying preview; payment control disabled; no ledger | Merchant/provider choice, sandbox integration, reconciliation |
| User onboarding | Access-key bridge; gated email candidate in existing Login/Account; phone always unavailable | Activate email only after store/secrets/delivery readback; SMS still has no provider |

Public Pricing follows `PRODUCT.md`: same base-data scope and history policy,
with rate-only tier differentiation. Monthly/annual switches show the actual
period total, monthly equivalent and savings. Displayed prices never grant
access. The sellable dataset set and its licence evidence still require
explicit review.

## Decisions required before implementation/activation

1. Both identity methods are confirmed; Resend and the dedicated email domain
   are selected. Still approve the identity store, least-privilege sending
   secret provisioning, and delivery/support ownership before email activation.
   SMS provider/signature/template remain deferred; do not expose an enabled SMS
   challenge or make SMS a prerequisite for email. No service purchase or contact
   upload is authorized by this draft.
2. Merchant entity and available merchant account, supported payment channels,
   settlement currency and sandbox credentials. Never request secrets in chat.
3. Prices, periods and manual renewal are confirmed. Still decide currency,
   tax/invoice handling, term boundaries, renewal stacking/upgrade rules, refund
   policy and failed-payment behavior.
   Do not invent defaults or treat annual billing as an automatic-renewal mandate.
4. Approved dataset scope shared by the tiers, including any category exclusions,
   and evidence of permissible customer redistribution.
5. Existing-key migration: verified ownership proof and account-binding rules;
   do not automatically attach an existing tenant by typed email or token label.

## End-to-end customer flow

1. **Sign in / register:** use one verified identity flow; generic send response,
   bounded resend/attempt rates, short expiry and one-time challenge consumption.
   No enumeration through different unknown/known-account responses.
2. **Account without a plan:** show identity plus an honest no-subscription
   state. No API data grant is minted just because registration succeeds.
3. **Choose an offer:** backend returns an immutable offer version, tier,
   currency, amount, period and included scope. The frontend cannot submit its
   own trusted price, tenant, expiry or authorization.
4. **Checkout:** backend creates a tenant-bound pending order and provider
   checkout intent. Payment page return is informational, never payment proof.
5. **Confirm payment:** verify provider signature and match merchant, order,
   amount and currency. Deduplicate notifications transactionally; preserve a
   reconciliation path for delayed or lost notifications.
6. **Activate:** only verified payment can schedule entitlement provisioning.
   Show `payment confirmed / activation pending` if provisioning fails. Use an
   idempotent control-plane operation; never pretend access exists prematurely.
7. **Use data:** Account reads effective subscription, expiry and dataset grants
   from the backend; users create separately scoped Agent/API keys.
8. **Renew / expire:** calculate from the authoritative entitlement expiry using
   the approved renewal rules, not the browser clock. No automatic renewal until
   explicit customer mandate and provider support are implemented and verified.

## Logical objects (not a committed database migration)

- User identity; verified identity credential; explicit tenant membership.
- One-time verification challenge with hashed secret, expiry and consumed state.
- Browser session with hashed opaque credential, expiry and revocation record.
- Offer version; tenant order; payment attempt; verified provider event.
- Subscription entitlement; provisioning attempt/outbox; audit/reconciliation
  record. Raw API keys never appear in commerce records or webhook logs.

Keep payment state (`pending`, `verified_paid`, `failed`, `refunded`) separate
from access state (`not_provisioned`, `provisioning`, `active`, `expired`,
`suspended`). These are draft internal concepts, not promised public enums.
Do not overload technical dataset entitlement with purchased subscriptions.

## Delivery sequence and gates

### Independent-account slice (local candidate, not activated)

Implemented locally within the existing Login/Account, independently of payment
activation: one-use email codes, independent revocable sessions and unsubscribed
account projection. See [email identity implementation contract](email-identity-v1.md).
The dedicated D1 store and Resend secrets still need production approval; legacy
tenant linking is deliberately absent, not inferred by matching email. SMS is a
later independent slice, not an email-launch requirement. This document does not authorize a
provider purchase, contact upload, production migration or secret change.

| Website identity | Data entitlement | Account experience |
| --- | --- | --- |
| Verified | None | Account and personal library available; data access not subscribed; no key creation/grant |
| Verified | Active | Show server-confirmed access, expiry, usage and separately scoped Agent keys |
| Verified | Expired/suspended | Account and saved materials remain accessible; data requests remain denied |
| Unavailable | Unknown | Retry identity verification; never infer signed-out or active access |

Required local/sandbox acceptance before activation:

- One-use verification, expiry, bounded retry/resend, generic known/unknown-account
  responses and atomic challenge consumption under concurrent attempts.
- Verified identity cannot claim another tenant; contact linking and existing-key
  linking require explicit ownership proof, never email/key-label matching.
- Session expiry/revocation is independent of API-key rotation or expiry. No
  silent logout from a data-usage outage; no grant minted by registration.
- Existing key holders retain the current bridge during a reviewed migration;
  no key replacement, deletion, or upload to the identity vendor.
- Cross-device bookmarks follow verified identity. Browser-local bookmarks stay
  local until a user explicitly imports them into the displayed account. Sign-out
  or account switching must clear any fetched private library from memory; no
  implicit import, cross-account merge or analytics event containing saved items.

Production email/SMS sending and persisted accounts remain disabled until service
configuration, abuse controls, reviewed storage/API boundaries and end-to-end
verification are complete. Local fixtures cannot claim a message was delivered.

### Release sequence

1. Sign-out and session-lifecycle work from PR #386 is merged. Production
   Account readback of an intended existing key remains a separate evidence
   step; key creation/disabling still needs a bounded separately approved test.
2. Keep the access-key bridge during migration. Do not treat Git merge of the
   pricing/identity contract as email activation or checkout.
3. Resolve the remaining decisions above, then choose the identity/commerce store and
   provider integrations through an explicit architecture review.
4. The local email-identity slice already exists as a gated candidate
   (`EMAIL_LOGIN_ENABLED=false`). Activation still requires approved secrets,
   delivery/abuse readback, and the [email identity](email-identity-v1.md)
   release gates. SMS remains a later independent slice.
5. Implement sandbox checkout with no production merchant writes. Test duplicate,
   forged, out-of-order, wrong-amount, cancelled, delayed and retried events plus
   entitlement provisioning failures and recovery.
6. Reuse current Login, Pricing and Account surfaces with loading, empty, failed,
   pending-activation and expired states. Test Chinese/English, light/dark,
   desktop/tablet/mobile and keyboard operation.
7. Activate production only after provider/merchant configuration, exact-code CI,
   limited approved transaction testing and independent payment/access readback.

## Rollback and safety

Identity and checkout entry points need independent feature switches. Disabling
new checkout must stop new purchases without deleting settled orders or breaking
existing paid access. Rollback cannot erase payments, reset subscriptions or
revoke existing API keys. Reconcile verified paid-but-not-provisioned orders
before retrying; do not issue duplicate access or duplicate charges.

Until those gates pass, keep purchase and unverified verification-sent claims
disabled. `/login` shows three methods: access-key (current production
bridge), email (only when `GET /api/account/auth-methods` returns
`email: true`; committed Worker config keeps this false), and phone (always
`phone: false`, no SMS provider). Unavailable methods must not collect
contacts or simulate a sent code. No fake invoice, placeholder amount,
guessed expiry or fabricated payment success may appear in the public product.
