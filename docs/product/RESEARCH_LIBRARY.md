# External research library

Last reviewed: 2026-08-30. Scope: the `public-web` PR candidate, not production.

## Purpose and acceptance

Research helps users move from a question to an attributed external source and
its data-preparation requirements. The current candidate target is 200 distinct
works/materials; a translation, working-paper duplicate, digest, edition link,
or reading-path membership is not an additional work.

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
2. Run `node scripts/verify-research-sources.mjs` in `public-web`. Review its
   unresolved report and inspect authoritative sources for exceptions.
3. Run `node --test tests/research-catalog.test.mjs`, `npm run test:sites` and
   `npm run build`. Review identity, duplicate, locale, source and related-link checks.
4. Inspect actual desktop/narrow rendering, language preferences, both themes,
   pagination, filters, global search, saved links and source/detail navigation.
5. Commit only scoped content/UI/docs/build changes through the feature PR.
   CI, merge and production publication are distinct states requiring fresh evidence.

This is a maintainable editorial workflow, not an automatic web-ingestion or
publication job. No recurring automation, provider call, account permission or
production collection change is introduced. A later update should state its
selection window and quality evidence instead of promising indefinite freshness.
