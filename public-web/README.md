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

Maintainer contract: [`docs/product/RESEARCH_LIBRARY.md`](../docs/product/RESEARCH_LIBRARY.md).
Current Git-merged snapshot (not a production publication claim): 200 works,
120 guides (119 six-section; Dechow/Dichev four-section), 80 summary-only,
85 comparison pairs, six synthetic `/recipes/:id` tutorials, 24 generated
downloads, 211 static HTML entries.

| Task | Command or file |
| --- | --- |
| Structural / editorial audit | `npm run audit:research` |
| Bounded link or Crossref check | `npm run audit:research -- --links` or `--metadata` (read-only) |
| Source-identity review (may write a report) | `node scripts/verify-research-sources.mjs` |
| Catalog and site tests | `npm run test:sites` |
| Project bodies + downloads | `npm run build` |
| Offline notebook arithmetic | `python3 scripts/verify-tutorial-notebooks.py` |
| Optional Jupyter kernel | `scripts/verify-tutorial-jupyter.py` in an isolated env |

Guide bodies assemble in `src/researchReaderNotes.js` (later spreads win).
Discovery rows come from `src/researchCatalog.js`. Production builds replace
`researchGuideLoader.js` and strip article bodies via
`scripts/research-public-projection.mjs`; development keeps the in-process
fallback. Do not hand-edit `dist/client`. Hash restore for lazy tutorials
cancels after 2s (`researchHistory.restoreLocationHashTarget`).

### Current library contents

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
