# External research library

Last reviewed: 2026-09-01 after PR #385 merged to `main`. Git now contains the
200-source library, 24 bilingual guides and three offline tutorials. Merge is
not a production publication claim: exact-main public-web deploy plus route,
share-metadata and download readback remain separate evidence. Local QA for the
candidate is in `docs/reports/2026-08-30-research-library-200-qa.md`.

## Purpose and acceptance

Research helps users move from a question to an attributed external source and
its data-preparation requirements. The accepted count is 200 distinct
works/materials; a translation, working-paper duplicate, digest, edition link,
guide, tutorial or reading-path membership is not an additional work.

Every record needs:

- Original title, authors/institution, venue, publication/version information,
  a stable source link and dated verification evidence.
- Independently written Chinese and English orientations and data requirements.
  Chinese editorial titles are labelled as unofficial, not full translations.
- Topic classification, applicable limitations, preparation checks and links to
  real maintained Data/Feature/Method objects. A link is methodological context,
  not evidence that TradingDatas covers the original sample or can reproduce it.
- An internal preparation state. New sources default to orientation only;
  underlying provider rights, activation and runtime evidence are unchanged.

Selection favors established methodological references, primary institutional
materials and empirical papers that make data requirements intelligible. The
library spans asset pricing, microstructure, fundamentals, research methods,
text/alternative data, macro-finance, Chinese/comparative markets and crypto.
Foreign-market literature is comparative context, not an expansion of TD's live
collection scope. The catalogue is not a systematic or exhaustive literature
review, and inclusion is not endorsement of a conclusion or trading strategy.

## Implemented surface

Reader routes live in `public-web` and stay on the content plane. They do not
call catalog/query, activate Recipe/Feature contracts, or change entitlements.

| Route | What the reader sees |
| --- | --- |
| `/research` | Featured: editorial lead, three four-record paths, 24 guides |
| `/research?view=topics` | Topics: eight subjects, format filter, 12 rows per page |
| `/research/:slug` | Article for one of the 200 records |
| `/research/paths/:id` | One of the three existing four-record paths |
| `/recipes` and `/recipes/:id` | Three bilingual preparation tutorials |
| `/downloads/research/:id/*` | Generated synthetic inputs, JS example, localized notebooks |

Topics query parameters are `view`, `topic`, `format` and one-based `page`.
Unknown values fall back; out-of-range pages clamp. Canonical share URLs use
the trailing-slash directory form `https://tradingdatas.com/<route>/`.

Maintainer files (edit these; do not hand-edit `dist/`):

| File | Role |
| --- | --- |
| `src/researchSeeds.js`, `src/researchLegacy.json` | Editorial identity seeds |
| `src/researchBibliography.json` | Crossref-normalized DOI records |
| `src/researchSourcePages.json` | Official pages without a usable DOI |
| `src/researchLookups.json` | Crossref query hints |
| `src/researchCatalog.js` | Assembles the 200 records |
| `src/researchEditorial.js`, `src/researchEditorialExpansion.js` | 24 four-section guides |
| `src/researchReaderNotes.js` | Reader notes and source-specific limits |
| `src/researchJourneys.js` | Eight three-step subject journeys |
| `src/researchDiscovery.js` | Featured/Topics URL state |
| `src/researchHistory.js` | In-tab scroll positions and hash restore |
| `src/preparationTutorials.js` | Tutorial copy and teaching fields |
| `src/tutorialExamples.js`, `scripts/tutorial-python/` | Shared JS/Python synthetic examples |

`npm run build` runs Vite, Sites preparation, then
`scripts/build-research-pages.mjs` (208 static HTML entries with bilingual
share metadata) and `scripts/build-tutorial-downloads.mjs` (three download
directories: `inputs.json`, `example.mjs`, `tutorial-zh.ipynb`,
`tutorial-en.ipynb`). The Vite plugin
`scripts/research-public-projection.mjs` strips internal
`evidence`/`verifiedAt`/`readiness`/`checks`/`limits`/`orientationMinutes`
from the public catalogue bundle. Source records still retain those fields.

## Sources and verification

`researchBibliography.json` stores normalized identity fields returned by
publisher-registered Crossref records, DOI/evidence URLs, check date and a hash of
the retained identity fields. The hash is **not** a full-paper or source-page hash.
Exact normalized titles and author identity must match; journal digests/reviews
must not replace the intended paper. Prefer the intended journal edition over
an earlier working paper, and label working papers/books/reports accurately.

`researchSourcePages.json` handles works without a suitable DOI record using a
publisher archive, original article, author institution or official issuer page.
Legacy official-source records retain their checked links and explicit version
notes in `researchCatalog.js`. A page check only establishes source identity and
observed version. Neither verification tier claims full-text peer review,
complete reading, replication or validation of the paper's conclusions.

Do not publish unresolved candidates. Resolve missing/wrong titles, authors,
versions, duplicates and broken source identities before count acceptance.
Review known corrections/retractions when encountered; do not infer their absence
from Crossref registration. Access/paywalls, licences and current official
methodologies must be reconfirmed for actual use. Never copy protected full text
or publisher abstracts into the public library.

The 2026-08-30 correction preserves the legacy China-market route/bookmark but
replaces its unsubstantiated display citation with Carpenter and Whitelaw's 2017
*The Development of China's Stock Market and Stakes for the Global Economy*.
The Chinese intraday paper is attributed to Chen, Cai and Ho. CSI's linked PDF
is the September 2023 methodology edition; SSE's 2025 volume describes 2024
statistics. Aave protocol inputs are not Binance perpetual funding/OI inputs.

## Language and discovery

The public detail page is an article, not a verification dashboard. Preparation
state, source-check timestamps/process descriptions and generic preparation
checklists remain internal. Readers see original authorship, direct source access,
browser-local bookmarking, a copyable original-language citation, editorial
orientation and specific reading limitations. Category-level limitations are not
presented as individual-paper analysis. Additional data/method links are optional
disclosure content, explicitly not the paper's original sample. Source-specific
reader notes and their internal review references live in `researchReaderNotes.js`.
`researchEditorial.js` and `researchEditorialExpansion.js` deepen 24 selected
guides across all eight reading journeys, with four bilingual sections and
source-specific limitations each. Every guide retains an internal evidence URL
and actual reading scope. Some use original/author-copy introductory sections;
others are deliberately abstract-based (including Kyle, Corwin/Schultz,
Nelson/Siegel and the Bitcoin overview). Dechow/Dichev and Replicating Anomalies
retain their final publication identities while explicitly explaining the use
of working-paper material. No draft numerical results are silently presented as
final results. This does not certify 200 full-length guides or 24 full-text reviews.

System language is the default; Account holds the System/中文/English override.
Reader titles, summaries, data requirements and authored limitations change
together. Original titles, author names, DOI, identifiers and source links remain
stable. Source sites/full text may be in another language; this is disclosed.

The confirmed reading views are Featured and Topics. Featured presents an editorial
recommendation and question-led paths; Topics exposes the complete library through
eight display subjects and publication-type filtering, in pages of 12. The existing
quant-methods and research-methods records share one display subject without
changing their stored identity. All three four-record reading paths stay reachable.
Global search covers both languages across all records; counts derive from records.
No reading-time estimate implies a full-paper reading or review.

Each subject has a three-stage introductory/core/deeper reading route in
`researchJourneys.js`, shown on the first unfiltered topic page. Some stages
deliberately bridge related subjects; this does not change original taxonomy or
counts. Featured also exposes the 24 expanded guides below the lead story.
Each journey has three distinct guides. Article sidebars show position and
previous/next readings with sixteen authored connections explaining differences
in questions, methods or evidence, not an implied author citation or ranking.
Three bilingual `/recipes/:id` tutorials teach adjusted prices, as-of filing
versions and event-calendar alignment using explicitly synthetic, local-only
examples. Publishing tutorials does not activate the underlying Recipe/Feature
product contract. Each tutorial offers synthetic inputs/expected results, a
standalone JavaScript file and a notebook in the selected language. All are
generated from maintained examples; Python code cells execute offline and are
tested against the JS output. No source paper PDFs, provider data or credentials
are redistributed. See `docs/design/research-reading-depth-v4.md` and
`docs/design/research-reading-continuity-v5.md`.

View changes preserve filters/page. Selecting a subject or all literature resets
format/page; format changes reset page. URL parameters reproduce view, topic, format
and page across reload/share; each in-tab library history entry retains its own
scroll position, and explicit article return restores the latest library view.
This is not synchronized reading history. Clipboard failure exposes selectable
citation text instead of claiming success. See `docs/design/research-dual-view-v3.md`.

Article share links use stable production canonical URLs. Build-generated HTML
for 200 records, three paths, three tutorials and both index routes supplies
bilingual title/description/Open Graph metadata before JavaScript; the SPA
updates metadata to the active language during navigation. This is share-preview
support, not server-rendered article bodies or proof of search-engine indexing.
The build omits internal evidence/check profiles from the public catalogue;
source records and validation still retain them. Tutorials load on demand.

Legacy official-source verification dates are stored per source; a library-wide
content update cannot advance those dates. Source identity checks and editorial
reading-note reviews are separate evidence, neither implies replication.

## Maintenance and verification

1. Add or revise editorial notes and identify the intended original work.
2. Run `node scripts/verify-research-sources.mjs` in `public-web`. Review
   `research-source-review.json` and inspect authoritative sources for
   exceptions. Default mode only fills missing or mismatched Crossref rows.
   `--refresh` re-queries Crossref at 1.5s per pending item and rewrites
   bibliography dates; do not use it for a routine content pass, and never let
   a library-wide refresh advance stored legacy official-source check dates.
3. Run `npm run test:sites` (includes `tests/research-*.test.mjs` and
   `tests/tutorial-*.test.mjs`) and `npm run build`. Then
   `python3 scripts/verify-tutorial-notebooks.py` against
   `dist/client/downloads/research/*/tutorial-*.ipynb`. The Python runner
   executes generated cells with the standard library only; it is not a
   Jupyter kernel or UI test.
4. Inspect actual desktop/narrow rendering, language preferences, both themes,
   pagination, filters, global search, saved links, article return, native
   Back/Forward and tutorial section hashes.
5. Commit only scoped content/UI/docs/build changes through the feature PR.
   CI, merge and production publication are distinct states requiring fresh evidence.

### Common pitfalls

- Hash restore in `researchHistory.restoreLocationHashTarget` waits up to 2s
  for lazy tutorial sections to mount, then `scrollIntoView`. Leaving that
  hash, or starting another restore, must cancel the pending observer; the
  late PR #385 commits exist because a stale restore scrolled the wrong page.
  `App.jsx` tracks native `hashchange` so Back stays in-page
  (`isInPageNavigation`) instead of treating a section link as a new route.
- Vite preview may serve the root SPA shell for some slashless URLs. Confirm
  share metadata on directory URLs (`/research/<slug>/`) and confirm
  trailing-slash behavior separately on Wrangler or the published Worker.
- Related Data/Feature/Recipe IDs are methodological context from
  `productManifest.js`. They are not catalog availability, entitlement, or
  Recipe Plane activation.
- Do not copy protected full text or publisher abstracts into seeds, guides
  or notebooks. Tutorial downloads are synthetic and generated; do not
  hand-edit `dist/client/downloads/`.

This is a maintainable editorial workflow, not an automatic web-ingestion or
publication job. No recurring automation, provider call, account permission or
production collection change is introduced. A later update should state its
selection window and quality evidence instead of promising indefinite freshness.
