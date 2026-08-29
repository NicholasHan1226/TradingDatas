# TradingDatas account and admin convergence v1

## Decision

TradingDatas has one customer-facing account experience and one restricted administrator console. It does not maintain a second customer portal with its own product navigation.

- The public product site remains the discovery and transparency layer: datasets, collection history, research, pricing, documentation, and public receipts.
- `Account` is the customer home: bookmarks, subscription and add-ons, effective access, usage, API credentials, Agent/MCP connection, billing, preferences, and security.
- The administrator console is an exception-and-control surface: customer access, runtime exceptions, aggregate usage, and authenticated data readback.
- Full collection catalogs and product stability stories are not duplicated in the administrator console. Operators start from unresolved exceptions; public product pages remain the readable source for dataset history and trends.

## Information architecture

### Account

1. Overview — plan, expiry, effective data categories, request frequency, and recent usage.
2. Data access — base package, alternative-data add-ons, trials, expiry, and category grants.
3. API keys — list, create, and disable same-tenant credentials. New keys inherit effective access; the raw secret is shown once and the current credential cannot disable itself. Rotation remains a guided create-and-disable sequence until a dedicated atomic rotation contract exists.
4. Agents and MCP — one-click setup guidance for supported Agents without embedding secrets in prompts.
5. Bookmarks — saved datasets, research, methods, and documentation.
6. Billing — orders, renewals, invoices, and payment records after commerce contracts exist.
7. Preferences and security — language, appearance, sessions, and access audit.

The current authenticated backend can truthfully supply account identity, entitlement, expiry, request limits, 30-day usage history, and customer-scoped key management through `/portal/api/me`, `/portal/api/me/usage`, and `/portal/api/me/keys`. Account Overview, Subscription, Usage, API Keys, and Security project only those authenticated facts. The current contract does not project alternative-data add-ons separately, so trial, add-on expiry, and renewal are labeled unavailable rather than inferred from broad category grants. Billing, a same-site passwordless session, and cross-device bookmark sync remain target surfaces until their backend contracts exist.

`/login` is the dedicated customer authentication entry. It verifies an existing TradingDatas access key against the same customer portal contract and sends a verified customer to `/account`. The public Worker now contains a disabled-by-default same-site session bridge: once its production encryption secret and upstream binding are configured, `/login` exchanges the key for an eight-hour encrypted `HttpOnly`, `Secure`, `SameSite=Strict` cookie and all Account reads/mutations stay on `tradingdatas.com/api/account/*`. Until that binding is enabled, the compatibility path keeps the key in `sessionStorage` for the current tab only. It migrates and removes the former `localStorage` value, so a long-lived key is no longer retained as persistent browser state. Signed-out Account actions and the header account icon route to this page. Email, SMS, password-reset, registration, durable cross-device sessions, and session-list/audit flows remain unavailable until the full identity contract exists; the interface must say so rather than simulate them.

The session bridge is a credential-containment migration, not the finished user identity system. Its production switch is deliberately absent from the committed Worker configuration. Enabling it requires a separately reviewed Cloudflare secret named `SESSION_ENCRYPTION_KEY`, a non-secret `ACCOUNT_API_BASE` binding, exact Worker deployment, and login/read/key-mutation/logout readback. Missing bindings return `503 identity_gateway_unavailable`; the current tab-only compatibility path remains available and the Worker never silently invents an account.

Before email or passwordless sign-in may replace the browser access-key entry, the backend contract must provide all of the following as one reviewed identity boundary:

1. A user identity store with a stable, server-owned user-to-tenant binding.
2. A verified email challenge sender with short-lived one-time challenges, replay protection, attempt limits, and audit evidence.
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

The existing `tradingdatas.com/account` surface is the only customer workspace, with `tradingdatas.com/login` as its authentication entry rather than a second portal. It reads the current account through the customer-scoped portal endpoints. When the same-site bridge is enabled, the page holds no readable bearer credential after exchange; the Worker decrypts it only while proxying the current request. The compatibility path is current-tab `sessionStorage`, never persistent `localStorage`. Credentials must not move into URLs, prompts, analytics, or public content. Customer-created keys are same-tenant, cannot inherit administrator scopes, and are shown once. The eventual email/passwordless identity gateway must reuse this same-site boundary without relying on a cross-site third-party cookie.

The React application under `static/app/` is administrator-only. Customer-scoped tokens are rejected there and directed to the existing public Account page; the old separate customer workspace is retired rather than redesigned.

The administrator console links out to the public Account instead of rendering an embedded customer preview. This keeps customer session state, customer navigation, and administrator authority visibly separate.

## Acceptance

- A customer sees `Account`, not a separate “customer portal” product.
- A signed-out customer enters through `/login`; successful verification restores the existing Account workspace without duplicating its navigation.
- An administrator sees four primary tasks: access, exceptions, usage, and verification.
- Public collection status is not copied into another full catalog inside admin.
- Every displayed live fact comes from authenticated portal/admin endpoints; unavailable capabilities are labeled as target surfaces.
- Login, Account, and admin visually match the current public TradingDatas language on desktop and mobile.
- Persistent `localStorage` never contains the Account access key; a configured same-site bridge uses an unreadable secure cookie, while an unconfigured bridge is explicit and falls back only to the current tab.
