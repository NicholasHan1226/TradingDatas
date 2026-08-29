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

The current authenticated backend can truthfully supply account identity, entitlement, expiry, request limits, usage, and customer-scoped key management through `/portal/api/me`, `/portal/api/me/usage`, and `/portal/api/me/keys`. Billing, a same-site passwordless session, and cross-device bookmark sync remain target surfaces until their backend contracts exist.

`/login` is the dedicated customer authentication entry. In the current release it verifies an existing TradingDatas access key against the same customer portal contract, stores that credential only in the current browser, restores the session on return, and sends a verified customer to `/account`. Signed-out Account actions and the header account icon route to this page. Email, SMS, password-reset, and registration flows remain unavailable until an identity contract exists; the interface must say so rather than simulate them.

### Administrator console

1. Customers and access — create, suspend, expire, and scope customer credentials.
2. Runtime exceptions — only failed, degraded, stale, or receipt-integrity cases that require action.
3. Usage — aggregate request trends and limit pressure; not a customer analytics product.
4. Data verification — authenticated catalog/query readback for operator confirmation.

The former full `Data pipeline` table is retired from primary navigation. Its data remains available to diagnostics, while the public Data and dataset-product pages carry readable collection status and history.

## Navigation and visual system

- Use the current TradingDatas public design as authority: warm neutral canvas, floating rounded navigation, quiet hairlines, blue/aqua accents, generous whitespace, and editorial typography.
- Do not inherit the previous dark finance-terminal rail or a generic SaaS dashboard layout.
- Account and admin use the same header, brand mark, spacing, radii, and type hierarchy as the public site.
- Dense tables are reserved for administrator mutation tasks. Customer pages prefer readable facts, timelines, and small product objects.
- Desktop and mobile must preserve the same task hierarchy; horizontal navigation may scroll, but primary actions cannot disappear.

## Authentication boundary

The existing `tradingdatas.com/account` surface is the only customer workspace, with `tradingdatas.com/login` as its authentication entry rather than a second portal. It reads the current account through the customer-scoped portal endpoints and stores the bearer token only in the current browser. Credentials must not move into URLs, prompts, analytics, or public content. Customer-created keys are same-tenant, cannot inherit administrator scopes, and are shown once. A future same-site identity gateway may replace browser token entry without changing the Account information architecture; it must not rely on a cross-site third-party cookie.

The React application under `static/app/` is administrator-only. Customer-scoped tokens are rejected there and directed to the existing public Account page; the old separate customer workspace is retired rather than redesigned.

Administrator preview shows only the administrator's own portal projection. It is not customer impersonation and cannot bypass server-side authorization.

## Acceptance

- A customer sees `Account`, not a separate “customer portal” product.
- A signed-out customer enters through `/login`; successful verification restores the existing Account workspace without duplicating its navigation.
- An administrator sees four primary tasks: access, exceptions, usage, and verification.
- Public collection status is not copied into another full catalog inside admin.
- Every displayed live fact comes from authenticated portal/admin endpoints; unavailable capabilities are labeled as target surfaces.
- Login, Account, and admin visually match the current public TradingDatas language on desktop and mobile.
