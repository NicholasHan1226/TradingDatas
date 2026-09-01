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
The public Worker rejects direct `/app`, `/app/`, and `/app/index.html` shell
requests while retaining `/app/assets/**` for the gated `/admin/` page. The
bearer-only `/app/` fallback exists only on the separate administrator Pages
origin, never on `tradingdatas.com`.

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

## Research library

The 2026-08-31 candidate contains 200 distinct external research materials with
Chinese/English editorial titles, orientations, data requirements and limitations.
These are attributed reading records, not 200 internally authored papers or
full-text translations. Bibliographic verification is not a full-text review,
replication, redistribution licence or production data-availability claim.
There are 120 bilingual guides: 119 have six located sections, while Dechow/Dichev
remains a four-section abstract-based orientation. The other 80 records are
summary-only. The eight three-stage core journeys retain their 24 original works.
`src/researchFiftyGuides.js` adds seven primary-source-located guides and
`src/researchSixtyGuides.js` adds ten more; `src/researchSeventyGuides.js` and
`src/researchEightyGuides.js` each add ten bounded primary-source guides. All 200 records now use explicit
per-work material selections (including intentional empty sets); unassigned
records fail closed to no materials, never topic defaults. The 150 previously
summary-only selections are in `src/researchSummaryMaterials.js`; this curation
does not constitute 150 full-text reviews. See
`../docs/design/research-120-guides-v15.md` for current source scope and acceptance.

`src/researchNinetyGuides.js` and `src/researchHundredGuides.js` add twenty further
bounded guides: eight asset-pricing, seven A-share/institutional-comparison and five
alternative-data records. They retain the earlier three preparation links and
seventeen intentional empty selections (75 linked records / 125 empty overall).
`src/researchComparisonExpansion.js` adds 36 explicit comparisons after the earlier
29, preserving their priority. Every guide has a comparison even after core-path
neighbors are excluded. The v15 packet separates executable checks, blocked real
browser acceptance, independent Datas PM approval and production release.

Production discovery retains both languages, stable IDs and `guideSectionCount`
but excludes article bodies. `ResearchArticle.jsx` requests one bilingual body
through `researchGuideLoader.js`, with loading/error/retry states, cancellation
of stale responses and section-fragment restoration after loading. Development
uses the full source modules. The build projection emits one dynamic module per
guide and fails if bodies are merged, missing or statically reachable from entry
chunks; its console report measures generated JavaScript bytes, not device speed.
No new API, analytics, account persistence or live-data request is introduced.
`src/researchFundamentalsMicrostructureGuides.js` adds six source-backed guides
on accounting signals, governance, distress and market microstructure. Source
edition differences are visible in locators/limitations; internal review notes
are not projected into articles.

`src/researchMethodsMarketsGuides.js` adds eight distinct guides on CAPM, five
factors, sentiment, crypto, policy uncertainty, HAC covariance, bootstrap and
Lasso; it also deepens the existing China market guide without counting it twice.
Actual source editions/pages and full-library maintenance results are recorded
in `../docs/design/research-forty-guides-v8.md`.

`src/researchCorporateGuides.js` adds three existing works on accrual-model tests,
residual-income valuation and financial-ratio classification. Three supplementary
question routes connect nine works on the company-topic page and article sidebars;
they do not replace core sequences or create duplicate records. Source reading
scopes and acceptance: `../docs/design/research-corporate-questions-v9.md`.
The editorial follow-up deepens Lazy Prices' document pairing/parsing and four
similarity definitions, governance coding exceptions and opt-outs, and the
abstract-supported firm-specific accrual method without increasing guide counts.
See `../docs/design/research-editorial-polish-v10.md` for the current audit and gaps.

`src/researchSeeds.js` holds new editorial notes; `src/researchLegacy.json` preserves
the original records and stable routes. `src/researchBibliography.json` is generated
publisher-registered metadata, and `src/researchSourcePages.json` records manually
checked primary-source exceptions. `src/researchCatalog.js` assembles the library,
shared preparation checks and three curated reading paths. See
[`RESEARCH_LIBRARY.md`](../docs/product/RESEARCH_LIBRARY.md) for acceptance rules.
The reader page keeps internal source-verification and preparation statuses out
of the public body. Source access, browser-local bookmarks and citation copying
are first-screen actions; clipboard failures offer selectable citation text.
`researchReaderNotes.js` holds source-specific editorial additions and internal
review references, without replacing bibliographic verification. Library filters,
page and scroll position survive in-tab article navigation. Filters and page also
survive reload through URL parameters; scroll position does not.
The confirmed Featured/Topics views share these records and article pages. See
[`research-dual-view-v3.md`](../docs/design/research-dual-view-v3.md) for behavior
and [`research-reader-v2.md`](../docs/design/research-reader-v2.md) for reader boundaries.

```bash
node scripts/verify-research-sources.mjs
node --test tests/research-catalog.test.mjs
```

The verifier reuses checked records and queries Crossref serially for missing or
invalid metadata. It exits nonzero and writes `research-source-review.json` when
editorial review is required; never auto-accept a fuzzy title or another author's
same-title digest. It does not download or republish full papers.

Language defaults to the primary system/browser language (`zh-*` -> Chinese,
otherwise English). Account preferences offer System / 中文 / English; explicit
choices persist in this browser. System mode responds to `languagechange` and
does not overwrite an explicit preference. Search indexes both editorial
languages and original titles regardless of the selected display language.
The complete library is available in Topics in pages of 12; global search
still searches all 200 records. Bookmarks and source routes remain language-neutral.

The original 24 bilingual guides
are in `src/researchEditorial.js` and `src/researchEditorialExpansion.js`;
`src/researchAdditionalGuides.js` adds Amihud and Novy-Marx using located primary
passages, without changing the eight core three-stage reading sequences.
`src/researchDeepReads.js` deepens eight of them, and
`src/researchGuideDepthExpansion.js` extends fifteen more using inspected primary
passages or author-issued supporting instructions. Subsequent batches above bring
the current total to 120 guides, 119 with six sections. The latest modules are
`researchMicrostructure120.js`, `researchCrypto120.js` and `researchMacro120.js`
(seven, seven and six guides). They retain edition-specific limits and the existing
per-work preparation selections. Nelson/Siegel uses the 1985 NBER working paper,
explicitly distinct from its 1987 journal citation. Dechow/Dichev retains four
abstract-based sections pending usable full-text evidence; section counts do not
certify complete reading. Eight subject
sequences and sixteen explanatory connections live in `src/researchJourneys.js`.
Each sequence has three guides, including intentional cross-subject readings.
Core articles show their position and previous/next reading with authored reasons;
`src/researchConnections.js` adds 85 authored comparison pairs across 121 works,
covering all 120 guides. Each article shows up to three bilingual
comparison reasons, excluding its existing previous/next links. These are editorial
contrasts, not inferred citation edges, agreement or evidence rankings. They work
from discovery metadata during body loading/error and preserve the core reading
order. Records without a sequence or a curated comparison retain same-topic links.
Amihud uses the 2002
journal article; Novy-Marx uses the June 2012 author draft, identified separately
from its retained 2013 journal citation. The Chinese title now distinguishes gross
profitability (gross profits/assets) from gross margin (gross profits/sales).
Six preparation tutorials (`preparationTutorials.js`, `preparationTutorialExpansion.js`, `tutorialExamples.js`) use
local synthetic examples, never real requests. Their publication does not change
the product manifest's underlying data/Feature/Recipe maturity or account grants.
See [`research-reading-depth-v4.md`](../docs/design/research-reading-depth-v4.md).
The current editorial follow-up is
[`research-editorial-polish-v10.md`](../docs/design/research-editorial-polish-v10.md),
continuing the tutorial/maintenance contracts in
[`research-depth-completion-v7.md`](../docs/design/research-depth-completion-v7.md) and
[`research-depth-quality-v6.md`](../docs/design/research-depth-quality-v6.md).
Library scroll positions are isolated per in-tab history entry; explicit article
return restores the latest library view. They are neither persisted nor synced.

The normal build also generates twenty-four offline download artifacts under
`dist/client/downloads/research/`: six synthetic input/expected-output JSON files,
six standalone JavaScript examples and twelve localized Python notebooks. The
notebooks embed the same fixtures, require Python 3.10+ standard library only for
computation, and open in an existing Jupyter environment. Source generation lives
in `scripts/build-tutorial-downloads.mjs` and `scripts/tutorial-python/`. Do not
edit generated notebooks. They do not fetch real data or embed credentials.

```bash
npm run build
python3 scripts/verify-tutorial-notebooks.py
npm run test:sites
```

The standard-library validator executes all code cells top-to-bottom and compares
results with the browser examples. It is not a Jupyter UI/kernel integration test.
The test suite requires `python3`, or `TD_NOTEBOOK_PYTHON` pointing at Python 3.10+.
For actual Jupyter-kernel acceptance, run `scripts/verify-tutorial-jupyter.py`
with an isolated Python containing `nbformat`, `nbclient` and `ipykernel`.
This optional acceptance runner uses that interpreter, local IPC and temporary
connection files, shuts down every kernel and does not rewrite shipped notebooks
or register a global kernel. Opening the Jupyter UI remains a separate check.
Download URLs are build output: review them with `npm run preview` after building,
not the source-only Vite dev server. Changing language selects the matching
notebook without changing any dataset identifier.

The normal build now projects only reader fields into the browser catalogue,
separates React and research-catalog cache chunks, lazy-loads tutorial execution UI, and generates
211 research/tutorial/index HTML entries with bilingual sharing metadata. Keep
these generated `dist/client` entries together with the current hashed assets;
do not hand-edit them. Static metadata supports link previews, not article-body
SSR or verified search indexing. Existing Sites packaging and Worker stay intact.

### Read-only editorial maintenance

```bash
npm run audit:research
npm run audit:research -- --links --limit=20 --offset=0 --timeout-ms=8000
npm run audit:research -- --metadata --limit=10 --offset=0 --timeout-ms=8000
```

The default is offline. Structural errors are separate from editorial review
candidates (including the 80 summary-only records, repeated/short paragraphs and
limited reading scope). Optional HTTPS link checks use system `curl`, at most two
concurrent requests, timeout/response-size limits and verified TLS; HEAD falls
back to a bounded GET for 405/501. Publisher metadata checks are serial, DOI-only
and capped at 50 records per invocation. They flag registered title/author/year/
venue changes and reported updates without rewriting identities. Offsets apply
to the sorted unique URL list for links and DOI-bearing catalog order for metadata.
Run the two modes separately when advancing batches.

404/410 are broken links; 403/429, network and timeout results remain unresolved,
not proof of deletion. For explicit `.pdf` / `.txt` URL paths, the report compares
the final response Content-Type with `application/pdf` / `text/plain`. A mismatch
(including an HTML shell returned with 200) is `unexpected_content_type`; missing
or generic binary types are `file_type_unconfirmed`. Query-string filenames do
not imply an expected format. These are review items, not automatic broken-link
declarations. The check uses headers only, does not authenticate file bytes, and
cannot detect every soft-404 or prove that the linked edition is the latest.
Even a matching type remains `reachable_not_content_verified`. Metadata matches do not validate
paper findings. Review warnings and incomplete external checks are visible in
JSON but do not fail the process; structural errors and observed broken links do.
Check the report, not just exit status. No files are written, no source dates are
advanced, and no recurring update, ingestion or publication job is installed.

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

When changing Login or Account session code, keep these contracts:

- Transport lives in `src/accountSession.js` and `worker/index.js`. Do not add a
  bearer fallback, persist the raw key, follow upstream redirects, or mint a
  cookie from HTTP 200 without `portal.tenant_id` and `portal.tier`.
- `getAccountViewState` is the only presentation mapping: `checking` while
  identity is in flight, `unavailable` for gateway/timeouts, `signed_out` only
  for a confirmed absent/invalid session. Usage failures must not sign the user
  out unless the usage call itself returns `signed_out`.
- `POST /api/account/session` `401` is `invalid_token` (stay on Login). `GET me`
  `401` is `signed_out`. Sign-out UI clears only after `DELETE` returns
  `{signed_out: true}`; otherwise keep Account and retry.
- Login return is `safeLoginDestination`: `/account` or an allowlisted
  `/pricing/preview?plan=&period=` path. Arbitrary `next` values are rejected.
- Regression tests: `tests/account-view-state.test.mjs`, `account-login.test.mjs`,
  `account-session-lifecycle.test.mjs`, and `account-signout.test.mjs`.

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

New email challenge/verification readiness also requires
`IDENTITY_RETENTION_ENABLED="true"`. Existing verified sessions, revocation,
logout, and scheduled cleanup remain usable when new email login is rolled back;
the coupled readiness check does not replace migration, cron, backlog, or runtime
readback gates.

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
