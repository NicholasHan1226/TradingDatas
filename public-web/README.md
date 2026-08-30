# TradingDatas public web candidate

Independent React/Vite candidate for the public `tradingdatas.com` product
experience. It does not replace the authenticated console under `frontend/`
or prove that the public domain, Pages route, DNS, HTTPS, commerce, account, or
API subdomain is live.

## Local development

```bash
npm install
npm run dev
```

The prototype includes the confirmed public-home visual direction, responsive
Data/Features/Recipes/Research/Pricing/Docs navigation, a task-oriented Data catalog with
the connected-interface index, collection-history ledger, reviewed candidate-source landscape and phased integration roadmap, and
alternative-data ordering proposal, an external-paper/industry-research/case
library with internal detail records, transparent Feature definitions, versioned
Recipe examples, three proposed A-share workflow packages, a platform-wide
searchable Docs hub with article routes, independent history-aware product pages, a grouped Account workspace
containing `zh-CN`/`en` and system/light/dark settings, and a client-only Agent
setup prompt flow. `src/productManifest.js` is explicitly a design contract;
Feature/PIT/commerce states are not runtime claims. Example receipt values and the
`api.tradingdatas.com` address are explicitly proposal/synthetic UI content,
not runtime evidence.

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

```bash
npm run build
npm run test:sites
```

## Research library

The 2026-08-30 candidate contains 200 distinct external research materials with
Chinese/English editorial titles, orientations, data requirements and limitations.
These are attributed reading records, not 200 internally authored papers or
full-text translations. Bibliographic verification is not a full-text review,
replication, redistribution licence or production data-availability claim.

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
page and scroll position survive in-tab article navigation (not a page reload).
See [`research-reader-v2.md`](../docs/design/research-reader-v2.md) for the design boundary.

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
The complete library is progressively revealed in pages of 20; global search
still searches all 200 records. Bookmarks and source routes remain language-neutral.

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
configuration. If either is missing, the bridge
returns `503 identity_gateway_unavailable`; in that state the UI uses a
current-tab-only `sessionStorage` compatibility connection and removes the
former persistent `localStorage` credential. See `docs/API.md` and
`docs/OPERATIONS.md`; a code deploy alone is not evidence that the secure session
path is active.

Pushes to `main` that change `public-web/**` run the repository Cloudflare
workflow. The workflow checks out the immutable source SHA, deploys the Worker,
then requires `/`, `/account/`, `/data/`, `/research/`, and `/pricing/` to return
HTTP `200`, retain the requested effective URL, and contain the exact JavaScript
asset referenced by that checkout. A local build or a successful upload alone is
not production evidence.
