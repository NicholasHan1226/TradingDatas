# TradingDatas account and admin convergence v1

## Decision

TradingDatas has one customer-facing account experience and one restricted administrator console. It does not maintain a second customer portal with its own product navigation.

- The public product site remains the discovery and transparency layer: datasets, collection history, research, pricing, documentation, and public receipts.
- `Account` is the private customer home: overview, subscription, effective access, usage, API credentials, billing and security. Public help/setup, browser-local bookmarks and upper-right language/theme preferences do not require login.
- The administrator console is an exception-and-control surface: customer access, runtime exceptions, aggregate usage, and authenticated data readback.
- Full collection catalogs and product stability stories are not duplicated in the administrator console. Operators start from unresolved exceptions; public product pages remain the readable source for dataset history and trends.

## Information architecture

### Account

1. Overview — plan, expiry, effective data categories, request frequency, and recent usage.
2. Data access — base package, alternative-data add-ons, trials, expiry, and category grants.
3. API keys — list, create, and disable same-tenant credentials. New keys inherit effective access; the raw secret is shown once and the current credential cannot disable itself. Rotation remains a guided create-and-disable sequence until a dedicated atomic rotation contract exists.
4. Usage — limits and request history.
5. Billing — orders, renewals, invoices, and payment records only after commerce contracts exist; payment remains paused.
6. Security — identity/session and access safety.

Public help shortcuts open `/docs`, `/docs/:slug` and `/connect`; `/bookmarks`
is the browser-local library. These are not private Account sections. The top
header is Data / Research / Pricing with guest-accessible
language/theme in its upper-right menu.

`/account` and `/account/:section` require a verified session. Unknown sessions
show checking; only confirmed guests redirect to `/login?next=` with their
allowlisted overview/subscription/usage/keys/billing/security destination. Login
restores that destination. Identity outages show retry instead of redirecting.

The current authenticated backend can truthfully supply account identity, entitlement, expiry, request limits, 30-day usage history, and customer-scoped key management through `/portal/api/me`, `/portal/api/me/usage`, and `/portal/api/me/keys`. Account Overview, Subscription, Usage, API Keys, and Security project only those authenticated facts. The current contract does not project alternative-data add-ons separately, so trial, add-on expiry, and renewal are labeled unavailable rather than inferred from broad category grants. Billing, a same-site passwordless session, and cross-device bookmark sync remain target surfaces until their backend contracts exist.

`/login` is the dedicated customer authentication entry. It verifies an existing TradingDatas access key through the same-site session bridge and returns to `/account`, its allowlisted private section, or an explicitly allowlisted non-paying purchase preview. With the required bindings configured, the bridge exchanges the key for an eight-hour encrypted `HttpOnly`, `Secure`, `SameSite=Strict` cookie; all Account reads/mutations stay on `tradingdatas.com/api/account/*`. There is no direct-bearer or browser-storage fallback. Startup removes legacy Account credentials from both `localStorage` and `sessionStorage`; users of those retired paths sign in again without changing their server keys or grants. Email, SMS, password-reset, registration, durable cross-device sessions, and session-list/audit flows remain unavailable until the full identity contract exists; the interface must say so rather than simulate them.

The session bridge is a credential-containment migration, not the finished user identity system. The committed Worker configuration contains the non-secret `ACCOUNT_API_BASE` binding; the deployment workflow injects `SESSION_ENCRYPTION_KEY` from the repository secret using the explicit public Worker configuration. Runtime activation still requires exact Worker deployment and independent readback; successful customer login/read/key-mutation/logout must be verified separately from unauthenticated checks. Missing bindings return `503 identity_gateway_unavailable`, without a fallback credential path or an invented account. Current release evidence belongs in `STATUS.md`, not in this design contract.

Before email or passwordless sign-in may replace the browser access-key entry, the backend contract must provide all of the following as one reviewed identity boundary:

1. A user identity store with a stable, server-owned user-to-tenant binding.
2. Verified email and phone challenge senders with short-lived one-time challenges, replay protection, attempt limits, and audit evidence. Both methods belong to one account; credential linking requires fresh verification and must never merge tenants by a typed contact string.
3. A first-party session exchange that returns an `HttpOnly`, `Secure`, and appropriate `SameSite` cookie without exposing bearer credentials to URLs, prompts, analytics, or persistent browser storage. The current encrypted bridge proves this browser boundary but does not replace the required stable identity store or revocation/audit model.
4. An explicit browser-origin allowlist and credential-aware CORS policy; the current wildcard bearer API is not a cookie-session contract.
5. Session list, revoke, expiry, and audit endpoints that remain tenant-scoped.
6. A migration path from browser-stored access keys that never sends the existing raw key to a new identity provider or displays it back to the customer.

### Administrator console

1. Customers and access — create, suspend, expire, and scope customer credentials.
2. Runtime exceptions — only failed, degraded, stale, or receipt-integrity cases that require action.
3. Usage — aggregate request trends and limit pressure; not a customer analytics product. The compatibility field `hourly` must be rendered from each row's actual `window_seconds`, so commercial 60-second limits and legacy 3600-second limits are never mislabeled.
4. Data verification — authenticated catalog/query readback for operator confirmation.

The former full `Data pipeline` table is retired from primary navigation. Its data remains available to diagnostics, while the public Data and dataset-product pages carry readable collection status and history.

## Navigation and visual system

- Use the current TradingDatas public design as authority: warm neutral canvas, floating rounded navigation, quiet hairlines, blue/aqua accents, generous whitespace, and editorial typography.
- Do not inherit the previous dark finance-terminal rail or a generic SaaS dashboard layout.
- Account and admin use the same header, brand mark, spacing, radii, and type hierarchy as the public site.
- Dense tables are reserved for administrator mutation tasks. Customer pages prefer readable facts, timelines, and small product objects.
- Desktop and mobile must preserve the same task hierarchy; horizontal navigation may scroll, but primary actions cannot disappear.

## Authentication boundary

The existing `tradingdatas.com/account` surface is the only customer workspace, with `tradingdatas.com/login` as its authentication entry rather than a second portal. It reads the current account through the customer-scoped portal endpoints. The page holds no readable bearer credential after exchange; the Worker decrypts it only while proxying the current request. Neither `sessionStorage` nor `localStorage` may retain Account credentials. Credentials must not move into URLs, prompts, analytics, or public content. Customer-created keys are same-tenant, cannot inherit administrator scopes, and are shown once. The eventual email/phone identity gateway must reuse this same-site boundary without relying on a cross-site third-party cookie.

Email-session logout carries the `user_id` currently displayed by the initiating
page as an expected-identity comparison. The Worker rejects a stale-tab mismatch
without revoking the newer cookie identity; the header never selects which user
or session to revoke. Public Account and the embedded administrator wrapper use
the same response receipt before clearing their local projection. The legacy
access-key cookie-clear path remains separate because it has no email identity.

The React application under `static/app/` is administrator-only. Customer-scoped tokens are rejected there and directed to the existing private Account page; the old separate customer workspace is retired rather than redesigned.

The administrator console links out to the private Account instead of rendering an embedded customer preview. This keeps customer session state, customer navigation, and administrator authority visibly separate.

## Owner identity and two workspaces

Owner-confirmed on 2026-08-30: the supplied account email is the intended platform
administrator identity and must also enter the existing private Account. Its literal
address belongs only to private provisioning context, not this public repository.
This is a role requirement, not evidence that the email was verified or that a role
was already assigned.

- One verified user identity, with the existing Account as the personal/customer
  workspace and an explicitly labelled administrator-console entry when authorized.
- No duplicate owner account, no separate customer portal, and no embedded customer
  impersonation view. Returning to Account shows only that identity's own data.
- Persist an explicit server-controlled administrator grant against the verified
  stable user ID. It is not a registration field, query parameter, client setting,
  email-prefix convention, or automatic grant to the first registrant.
- Every privileged request must validate the live session, enabled user and current
  role. Role removal must stop subsequent admin access without waiting for cookie
  expiry. Public Account access may continue if the identity itself remains enabled.
- Administrator role and commercial subscription/data grants are separate. Do not
  infer paid entitlement or attach an existing tenant from an email or token label.
- Do not expose a shared administrator bearer key to the browser or replace existing
  keys to implement shared sign-in. The backend trust boundary, admin-origin/session
  handoff, audit attribution and role-provisioning path require a reviewed contract.

Current gap: the email candidate returns only verified, unsubscribed identities;
the existing admin frontend still requires its own admin/internal credential.
Neither a verified sending domain nor a delivered test email closes this gap.
Keep these facts explicit until real shared-login and privileged-request readback.

Acceptance must cover owner and ordinary-user login, forged role/email rejection,
unauthorized direct admin requests, immediate role removal, expiry/replay/sign-out,
and a return to the same Account without a second identity or leaked credentials.

## Acceptance

Account sign-out has one shared pending/error state across Overview and Security.
The session path clears account state only after `DELETE /api/account/session`
returns a successful JSON response with `signed_out: true`. Network failure,
non-success HTTP, malformed confirmation and a ten-second timeout leave the UI
in an explicitly unconfirmed state with a retry action; they never claim logout.
Requests are single-flight and older account reads are invalidated after success.
There is no tab-only compatibility path. Clearing the cookie does not implement
server-side revocation of a previously copied session.

- A customer sees `Account`, not a separate “customer portal” product.
- A signed-out customer enters through `/login`; successful verification restores the existing Account workspace without duplicating its navigation.
- An administrator sees four primary tasks: access, exceptions, usage, and verification.
- Public collection status is not copied into another full catalog inside admin.
- Every displayed live fact comes from authenticated portal/admin endpoints; unavailable capabilities are labeled as target surfaces.
- Login, Account, and admin visually match the current public TradingDatas language on desktop and mobile.
- Neither browser storage mechanism retains Account credentials. An unconfigured bridge shows unavailable and never downgrades to a direct-bearer request.
