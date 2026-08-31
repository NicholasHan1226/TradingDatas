# TradingDatas public web candidate

Independent React/Vite candidate for the public `tradingdatas.com` product
experience. It does not replace the authenticated console under `frontend/`
or prove that the public domain, Pages route, DNS, HTTPS, commerce, account, or
API subdomain is live.

## Local development

Use Node 22.13 or newer for the local checks (email-identity tests use built-in
`node:sqlite`). No SQLite test dependency is shipped to the browser or Worker.

```bash
npm install
npm run dev
```

The prototype includes the confirmed public-home visual direction, responsive
Data/Features/Recipes/Research/Pricing/Docs navigation, a task-oriented Data catalog with
the connected-interface index, collection-history ledger, reviewed candidate-source landscape and phased integration roadmap, and
alternative-data ordering proposal, an external-paper/industry-research/case
library with internal detail records, transparent Feature definitions, versioned
Recipe examples, three base-data request-rate tiers with confirmed monthly/annual
price display (checkout not yet available), a platform-wide
searchable Docs hub with article routes, independent history-aware product pages, a grouped Account workspace
containing `zh-CN`/`en` and system/light/dark settings, and a client-only Agent
setup prompt flow. `src/productManifest.js` is explicitly a design contract;
Feature/PIT/commerce states are not runtime claims. Unbound dataset pages show
unverified evidence, not invented percentages, successful collection timestamps
or historical coverage. Samples and the separate receipt illustration are
labelled synthetic beside the content. Product slugs are not API dataset IDs.

Agent setup is lazy-loaded and derives both authored languages directly from
`../docs/AGENT_INTEGRATIONS.md`; update that document rather than duplicating
prompts in components. The optional public build setting
`VITE_TRADINGDATAS_API_BASE_URL` accepts a reviewed HTTPS origin only, without
credentials, paths, query or fragment. Leave it absent until the service origin
is confirmed: the dialog then copies a clearly labelled draft with a placeholder.
Configuration is not connection verification or proof of a deployed MCP server.
The dialog never transmits a data request or reads a credential.
See [evidence and Agent readiness](../docs/design/public-evidence-readiness-v1.md).

The candidate landscape is maintained research, not an exhaustive list of every
global API. Technical reachability, redistribution rights, runtime activation,
receipt-backed availability and sellable package eligibility remain separate
states. See [`docs/product/DATA_SOURCE_LANDSCAPE.md`](../docs/product/DATA_SOURCE_LANDSCAPE.md).

Regenerate and verify the public contract/config snapshot after the provider
registry changes:

```bash
python scripts/build-connected-interface-snapshot.py
python scripts/build-connected-interface-snapshot.py --check
```

## Checks

Account continuity candidate: the existing `/account` can explicitly connect an
already-issued data key and use a separate authenticated personal library. The
existing administrator app is reused at `/admin/` via a same-origin authorized
gateway; no new customer dashboard. Flags `ACCOUNT_CONNECTION_ENABLED`,
`ACCOUNT_LIBRARY_ENABLED`, `ACCOUNT_ADMIN_ENABLED` all default false. Additive
`worker/account-library-schema.sql` has **not** been applied remotely. No new
subscription, production identity, admin grant or email delivery is asserted.
See [contract and acceptance gates](../docs/design/account-library-v1.md).

When admin source changes, first run `npm ci && npm run build` in `../frontend`.
Its versioned `../static/app` output is copied into the public build's `/app/`
asset directory; the Worker serves that shell at the gated `/admin/` route.
Standalone Pages `/app/` remains its existing bearer-only admin fallback.

Purchase preparation: `/pricing` opens the non-paying
`/pricing/preview?plan=basic&period=monthly`. Six combinations share `src/pricing.js`;
selection survives refresh and login via a strict same-site return allowlist.
It never creates orders or changes grants. Account billing remains unavailable.
Payment onboarding is paused; no merchant calls or live purchase switch exist.
See [flow and resumption gates](../docs/design/payment-flow-preparation-v1.md).

```bash
npm run build
npm run test:sites
```

Keep the generated raster assets in `public/assets/`. Do not rebuild the brand
mark or data-material artwork with CSS, inline SVG, or placeholder elements.

## Production release

The public website is deployed to the existing Cloudflare static-assets Worker
named `tradingdatas`. `public-web/wrangler.jsonc` binds the committed
`dist/client` build to the small SPA fallback Worker in `dist/server/index.js`.
For direct navigation, that Worker serves the app shell for extensionless
`GET`/`HEAD` routes outside `/api/` and `/assets/`, even when a generic client
does not send `Accept: text/html`; the Worker fetches the root app shell
internally, so the requested deep-link URL is retained. Missing API routes,
assets, extensionful files, and non-navigation methods remain ordinary
fail-closed `404`s.

The Worker also contains the same-site Account session bridge under
`/api/account/*`. `ACCOUNT_API_BASE` is committed as the non-secret production
binding, while the deployment workflow writes `SESSION_ENCRYPTION_KEY` from the
GitHub repository secret of the same name using the explicit public Worker
configuration. If either is missing, authentication returns
`503 identity_gateway_unavailable`; there is no direct-bearer downgrade.
Same-origin sign-out still clears the cookie during an upstream/config outage.
The UI removes former `localStorage` and `sessionStorage` credentials, so legacy
direct sessions must sign in once again; server keys and grants are unchanged.
See `docs/API.md` and
`docs/OPERATIONS.md`; a code deploy alone is not evidence that the secure session
path is active.

`/login` shares the existing Account workspace and brand. Access-key login uses
only the encrypted same-site bridge. Phone stays unavailable. Email enables only
when the Worker reports complete configuration; otherwise it collects no contact
details and does not simulate sending. The new, locally tested email identity is
independent of API keys and displays `not_subscribed` in the existing Account.
It cannot mint data grants or attach a legacy tenant. Identity and usage availability are
separate: a usage failure must not sign out an otherwise authenticated account.
Requests have timeouts; session changes invalidate late reads/key-write UI results.
While identity is being checked, private Account panels show a neutral verification
state instead of a sign-in prompt or cached credentials. Identity outages show a
retry action, not a false signed-out conclusion; public bookmarks, docs and
preferences remain accessible from the same workspace.

Local synthetic UI verification: `npm run build`, then
`node scripts/login-qa-server.mjs` and open `http://127.0.0.1:5193/__qa`.
The harness binds only loopback, is single-reviewer, never calls upstream, and
accepts only synthetic test strings for review. It is not a production login test.
Use `TRADINGDATAS_QA_PORT=5194 node scripts/login-qa-server.mjs` for an isolated
purchase-flow review while another login harness is running. Binding stays loopback.

Email identity review: after building, run `node scripts/preview-email-identity.mjs`
and open `http://127.0.0.1:5195/login`. Use an `@example.com` fixture; codes appear
only in the local synthetic mailbox at `/__test__/mail`, never in a real inbox.
The in-memory store resets on restart; no production secrets are used.
`/__test__/viewport?width=390` or `?width=768` renders a nested Account viewport
for responsive review; it is local-only and uses the same synthetic session.
Optional
local workerd/D1 verification and the production approval gates are documented in
[Email identity v1](../docs/design/email-identity-v1.md). The schema file and review
harness are not public assets. The dedicated remote account DB has been initialized;
the candidate `wrangler.jsonc` binds it as `IDENTITY_DB` but explicitly keeps
`EMAIL_LOGIN_ENABLED="false"`. On August 31, sender/pepper secrets were privately
prepared in an **undeployed** Worker version; the live version and identity binding
were not changed. See the [private provisioning checkpoint](../docs/reports/2026-08-31-identity-private-provisioning.md)
for the exact version and release gates. Do not deploy that old-code preparation
version as the email implementation or assume its secrets survive a later upload.
SMS and payments stay unavailable.

Account deletion stays inside the existing Account → Security panel. It requires
fresh email verification and explicit `DELETE` confirmation; success means the
request was accepted and every email session revoked, not that profile cleanup
has already finished. Legacy API keys, financial data and browser-local bookmarks
are outside this account-only action. The owner-approved active-store maxima are
24 hours for expired OTP records, seven days for invalid sessions, and 30 days
after a profile deletion request. See [retention contract](../docs/design/identity-retention-v1.md).
The new hourly maintenance job is gated by `IDENTITY_RETENTION_ENABLED="false"`;
both it and email login remain off. `worker/identity-retention-schema.sql` is an
additive migration for the dedicated account DB only, applied and read back on
August 31 with zero users/sessions/deletion requests and no foreign-key violations.
Tests/harnesses apply it after `worker/identity-schema.sql` to disposable stores.
No change here deploys a timer, deletes real users, or enables linked-account deletion.

All external email uses the versioned brand templates in `worker/email-templates.js`,
with explicit HTML and plain text. Sign-in and delivery-test variants support Chinese
and English; the login sender supplies the actual challenge expiry. On every send
and resend, email language follows the primary device/browser language (`zh` or
`zh-*` -> Chinese, otherwise English), independently of the website language toggle.
No locale is inferred from the recipient address. See
[Transactional email system v1](../docs/design/transactional-email-system-v1.md).
Run `npm run preview:email` for the read-only loopback gallery at
`http://127.0.0.1:5196/` (override with `TD_EMAIL_PREVIEW_PORT`). Its code is an
invalid fixture; the gallery cannot send mail and is not shipped as a public route.
It supports language, simulated light/dark, narrow widths, image-blocked and text
previews. Actual QQ/Gmail/Outlook rendering still requires separately authorized mail.

Pushes to `main` that change `public-web/**` run the repository Cloudflare
workflow. The workflow checks out the immutable source SHA, deploys the Worker,
then requires `/`, `/account/`, `/data/`, `/research/`, and `/pricing/` to return
HTTP `200`, retain the requested effective URL, and contain the exact JavaScript
asset referenced by that checkout. A local build or a successful upload alone is
not production evidence.
