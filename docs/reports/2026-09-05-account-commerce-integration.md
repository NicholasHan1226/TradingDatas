# Account commerce integration acceptance

Scope: separate subscription/order read surface in existing Account, isolated
durable commerce simulator, and Docs naming. No production merchant, checkout,
commerce database, live payment, real entitlement or identity permission change.
The current contract is [Customer identity and commerce](../design/customer-identity-commerce-v1.md).

## Local evidence

- 313 public-web tests passed, including identity/connection regressions and
  50 focused backend tests. Production build and source-to-Worker packaging checks
  passed. Backend/frontend reviews found and fixed offer-version drift, omitted
  immutable term snapshots and the 20-order display limit.
- Offers derive from the single price source; version changes with price/currency/
  period/rate/terms. Orders save immutable price, rate and term snapshots.
- Tests cover ownership, revoked sessions, cross-origin writes, unknown/malformed
  state, unavailable commerce, reused keys, concurrent creation, duplicate and
  conflicting events, wrong amount/currency/verifier rejection, provisioning
  failure/retry, old terms and durable reopen. No test claims real provider signing.
- Actual browser synthetic flow: private billing redirects to login and returns
  after verification; create order, refresh, operator-only simulated settlement,
  subscription/expiry and distinct payment/activation readback. Dedicated local
  identity and commerce files preserve identity ownership on restart.
- Chinese/English and light/dark reviewed. Real nested 390px and 768px layout
  viewports had matching client/scroll widths, with readable order/status layout.
- Commerce-unavailable preview keeps identity and existing-key connection visible;
  it does not assert no historical payment. Production has no sandbox bindings.
- Docs remains public under unchanged paths, reached from Account, not primary nav.
  Old current-document claims that email/connection were disabled were removed.

- Final browser regression found duplicate React sibling keys after connecting an
  existing data account. Namespaced commerce keys fix the repeated panels.
  Fresh synthetic login, connection, record refresh, billing/subscription switches
  and page reload each retain one commerce region with no console warnings/errors.
  The rebuilt candidate again passes all 313 tests.

## Release boundary and remaining evidence

This is simulator development, **not payment-provider sandbox integration**.
Real recipient/ordinary customer access and merchant/settlement configuration
are still pending. No actual OTP was sent in this acceptance, no real customer key
was created, and no real payment or data grant was made. Public release and
financial runtime are independently recorded in STATUS after actual readback.

Rollback restores the prior public Worker while retaining identity/connection
state and existing customer keys. There is no production commerce migration to
reverse. Local simulator files remain outside the repository. Existing catalog
quality and collection continue independently of merchant inputs.

## Public release evidence

PR #495 merged as `e5e374a24b341fd27bb5b31fc2f98cef20d2d9d4` after all four
candidate checks passed (33964732178). Cloudflare run 33965231922 succeeded.
At 20:10 Asia/Shanghai on September 5, the real public page loaded
`index-qtd5VsfW.js`; Docs was public and in the Account menu, and guest billing
redirected to `/login?next=%2Faccount%2Fbilling`. Auth methods still reported
email enabled, phone disabled. Guest commerce/offers/orders returned JSON 404;
an explicitly invalid email-session cookie returned 401 for commerce. Guest
catalog returned 401. Private API responses were no-store; no order was created.
This confirms the public deployment and negative authorization boundaries, not
real customer sign-in, a live commerce ledger or paid activation.
