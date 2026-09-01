# External research library

Last reviewed: 2026-09-01. Scope: the `public-web` PR candidate, not production.

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
`researchEditorial.js` and `researchEditorialExpansion.js` provide 24 selected
guides across all eight reading journeys. `researchDeepReads.js` overrides eight
representatives; `researchGuideDepthExpansion.js` adds supported detail to fifteen
more without mutating their original four-section records. `researchAdditionalGuides.js`
adds two six-section guides for existing Amihud and Novy-Marx records. The current
library has 160 guides: 159 have six bilingual sections with source locators;
Dechow/Dichev remains a four-section,
abstract-based orientation pending usable full text. Nelson/Siegel's additions use
the March 1985 NBER working paper, with public edition-specific locators and limits
that distinguish it from the retained 1987 final publication identity. All retain
source-specific limitations and internal evidence URLs/actual reading scopes.
Scope varies: original passages, author copies, publisher previews, and (for
Corwin/Schultz) author-issued program instructions and appendix explanations are
not equivalent to complete paper review. Bitcoin's added detail uses a 2014 author
draft; Lazy Prices uses the March 2019 revision; Petersen uses the June 2006 NBER
revision. Their public limitations identify these editions. Dechow/Dichev and
Replicating Anomalies also preserve final publication identity separately from
working-paper material. No draft numerical results are silently presented as final
results. Amihud uses the 2002 journal article hosted by Penn; Novy-Marx uses the
June 2012 author draft hosted by Rochester, explicitly distinct from the 2013
journal citation. Its Chinese editorial title now says 毛利能力 rather than 毛利率:
the measure divides gross profits by assets, not sales. Source identities are unchanged.
`researchFundamentalsMicrostructureGuides.js` adds six existing works: Piotroski,
Gompers/Ishii/Metrick, Campbell/Hilscher/Szilagyi, Roll, Hasbrouck and
Cont/Kukanov/Stoikov. Their sections cover bounded questions, definitions,
information timing and methodological limits, not numerical replication.
Governance uses the August 2001 NBER draft rather than the 2003 journal version;
distress uses the June 27, 2005 author draft rather than the 2008 final article;
order-book events uses frozen arXiv v3 (March 2011), distinct from the 2014
journal citation. Each difference is public. Internal evidence scopes record
only the pages actually read; image-only Hasbrouck and encoded governance scans
were visually read. No PDFs are redistributed.
The methods/markets continuation in `researchMethodsMarketsGuides.js` adds eight
new guides and replaces the existing China market guide with more specific
measurement explanations, never counting that replacement as another work.
CAPM, five factors, sentiment, EPU, bootstrap and Lasso use journal editions;
crypto uses the August 2018 working paper and Newey–West the February 1986 revised
working paper, distinguished from their 2021/1987 canonical citations. Source
pages inspected and maintenance findings are in `docs/design/research-forty-guides-v8.md`.
The corporate continuation in `researchCorporateGuides.js` adds three existing
works: Dechow/Sloan/Sweeney's model comparison, Ohlson's valuation framework and
Altman's discriminant analysis. They distinguish abnormal accruals, residual
earnings and bankruptcy scores; source pages and acceptance are documented in
`docs/design/research-corporate-questions-v9.md`.
This does not certify 200 full-length guides or 160 full-text reviews; 40 works
remain summary-only.
The editorial pass in `docs/design/research-editorial-polish-v10.md` retains those
then-current counts while replacing generic passages in Lazy Prices with source-located
document pairing, parsing and similarity definitions, and in governance with
reverse coding, equal weights and firm-level opt-outs. Dechow/Dichev remains
abstract-based, now explicitly identifying firm-specific estimation and linking
the accessible abstract. Its unsuccessful full-text retrieval is not a new review.

`researchFiftyGuides.js` adds seven existing works on systemic risk, leverage,
text, geopolitical risk, random forests, Chinese warrants and DeFi, based on
bounded primary-source passages. Edition and reading boundaries are recorded in
`docs/design/research-fifty-guides-v11.md`; no whole-paper review is implied.
All 200 records now have deliberate per-work material selections:
new-guide `related` overrides take precedence over `researchGuideMaterials.js`,
then `researchSummaryMaterials.js`, then an empty object. No topic fallback is
used. An explicit empty object suppresses the
related-material disclosure; no material is better than a misleading match.
All 150 previously summary-only records were curated against their existing
orientations and data requirements. This is navigation curation, not full-text
review or endorsement. Ten now have additional source-located guides in
`researchSixtyGuides.js`: elastic net, Taylor rules, principal components, PBO,
China size/value, discount rates, equity-premium prediction, Flash Boys, Aave V2
and Schär's DeFi survey. China size/value focuses on the author's variable
appendix, not the main empirical results. Source editions, read pages and current
acceptance for that batch are in `docs/design/research-delivery-v12.md`.
Two further batches in `researchSeventyGuides.js` and `researchEightyGuides.js`
add twenty existing works on volatility, inference, liquidity, attention, financing,
macro-finance and blockchain economics. Each has six bilingual, source-located
sections with actual edition and reading limits. All twenty intentionally have no
material links; this avoids implying maintained original samples or replication
inputs. That batch's source scope: `docs/design/research-eighty-guides-v13.md`.
The next twenty in `researchNinetyGuides.js` and `researchHundredGuides.js` cover
eight asset-pricing, seven A-share/institutional-comparison and five alternative-data
records. Every section has an edition-specific locator. The existing Fama/MacBeth
price-preparation and two text-versioning links remain preparation examples only;
the other seventeen selections are deliberately empty. Overall material coverage
stays 75 linked / 125 empty. `researchComparisonExpansion.js` adds 36 comparisons
after the previous 29; those 100 guides remain covered after core-neighbor exclusions.
The next twenty in `researchMicrostructure120.js`, `researchCrypto120.js` and
`researchMacro120.js` add seven microstructure, seven crypto and six macro guides.
Their explicit material selections remain unchanged; no new original-sample or
replication claim is introduced. `researchComparisons120.js` adds twenty pairs,
bringing the total to 85 across 121 works and covering every guide after exclusions.
Current source ledger and independent acceptance packet:
`docs/design/research-120-guides-v15.md`. The 2026-09-01 continuation adds twenty
existing catalog identities in `researchBatchTwo160.js`: six market-microstructure,
six corporate-fundamentals, three methods, one text/alternative-data, one
asset-pricing, one macro-finance and two crypto-market guides. Each is a bounded
bilingual orientation tied to its DOI or primary archive page; it does not claim
full-text review, replication, a current market conclusion, or new data coverage.
Source selection and checked primary pages are recorded in
`docs/design/research-160-guides-v16.md`. Blocked browser checks, pending Datas PM
review and predecessor integration are not represented as release acceptance.
Daily high/low and illiquidity guides link to daily data rather than minute bars;
text guides link to document versioning. No available order-book, governance,
token-adoption or general model-fitting tutorial is implied. Related materials
remain further exploration, not original samples or a replication bundle.

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

The shared `GlobalSearchField` gives desktop/mobile inputs distinct IDs and an
explicit label independent of the clear button. Typing does not change the input's
accessible name; clearing resets active selection and returns focus to that input.

Each subject has a three-stage introductory/core/deeper reading route in
`researchJourneys.js`, shown on the first unfiltered topic page. Some stages
deliberately bridge related subjects; this does not change original taxonomy or
counts. Featured also exposes the 160 expanded guides below the lead story.
The eight core sequences retain their original 24 distinct guides; additional
guides do not invent a fourth stage or change original sequence membership.
`researchConnections.js` supplies 85 explicit, symmetric editorial comparison
pairs across 121 works, covering the first 120 guides; newer guides retain the
same-topic fallback until an explicit comparison is authored. They contrast definitions,
inputs or methods; they do not assert citations, agreement, replication or evidence
ranking. The reader shows at most three comparisons with bilingual reasons and
excludes already displayed previous/next sequence links. Matching uses stable
catalog identities resolved from authored titles; missing matches fail closed.
Metadata is sufficient, so comparison navigation remains available while article
text is loading or has failed. Without a sequence or curated comparisons, the
existing same-topic fallback remains. No new route, API or stored preference.
Three supplementary corporate question routes in `researchQuestionRoutes.js`
connect nine existing works around earnings quality, company comparison and
financial distress. They appear as closed disclosures on the first unfiltered
company-topic page and as an expanded relevant route in member articles, marking
the current reading. They use existing article URLs, add no work identities or
new routes, and do not imply that adjacent papers validate each other. The
original eight core sequences and three curated path pages remain unchanged.
Expanded guides also have a collapsed contents disclosure before their body,
including on narrow screens. Section fragment IDs are locale-neutral and native
links target focusable sections with clearance beneath the floating header.
Each journey has three distinct guides. Article sidebars show position and
previous/next readings with sixteen authored connections explaining differences
in questions, methods or evidence, not an implied author citation or ranking.
Six bilingual `/recipes/:id` tutorials teach adjusted prices, as-of filing
versions, event-calendar alignment, minute-bar gaps, document-version ledgers
and spot/open-interest observation alignment using explicitly synthetic, local-only
examples. Publishing tutorials does not activate the underlying Recipe/Feature
product contract. Each tutorial offers synthetic inputs/expected results, a
standalone JavaScript file and a notebook in the selected language. All are
generated from maintained examples; Python code cells execute offline and are
tested against the JS output. No source paper PDFs, provider data or credentials
are redistributed. See `docs/design/research-reading-depth-v4.md` and
`docs/design/research-reading-continuity-v5.md` and
`docs/design/research-depth-quality-v6.md` and
`docs/design/research-depth-completion-v7.md`.

View changes preserve filters/page. Selecting a subject or all literature resets
format/page; format changes reset page. URL parameters reproduce view, topic, format
and page across reload/share; each in-tab library history entry retains its own
scroll position, and explicit article return restores the latest library view.
This is not synchronized reading history. Clipboard failure exposes selectable
citation text instead of claiming success. See `docs/design/research-dual-view-v3.md`.

Article share links use stable production canonical URLs. Build-generated HTML
for 200 records, three paths, six tutorials and both index routes supplies
bilingual title/description/Open Graph metadata before JavaScript; the SPA
updates metadata to the active language during navigation. This is share-preview
support, not server-rendered article bodies or proof of search-engine indexing.
The build omits internal evidence/check profiles from the public catalogue;
source records and validation still retain them. Tutorials load on demand.
Production research discovery also omits body paragraphs and expanded-guide
limitations while retaining both languages and `guideSectionCount`. Article
bodies load in one bilingual module per guide, independent of locale choice.
Loading and retryable failure keep identity/source actions visible; cancelled
article requests cannot overwrite the current article. Valid section fragments
are restored after content appears. The build rejects eagerly imported, merged
or missing body chunks. Byte/import-graph checks are not browser performance or
accessibility acceptance, and browser acceptance remains required before release.

Legacy official-source verification dates are stored per source; a library-wide
content update cannot advance those dates. Source identity checks and editorial
reading-note reviews are separate evidence, neither implies replication.

## Maintenance and verification

Use `npm run audit:research` for read-only structural and editorial checks before
refreshing any source metadata. `--links` adds bounded URL checks; `--metadata`
compares a bounded DOI batch with current publisher-registered metadata. These
commands report unresolved access and potential version changes without writing
files or changing source-check dates. Explicit PDF/text download paths also get
a final Content-Type check: HTML or other mismatches require review; missing or
generic binary types remain unconfirmed. Matching headers are not full-text or
file-byte verification. Limits, offsets and interpretation are in
`public-web/README.md`. Summary-only records and limited-reading scopes are
editing candidates, not automatically defective works; HTTP success and length
are never a quality certificate.
The existing internal-note guard applies to bilingual headings, summaries,
limitations and reference labels as well as section paragraphs. Internal evidence
scopes remain separate and are not subjected to this reader-prose check.

1. Add or revise editorial notes and identify the intended original work.
2. Run `node scripts/verify-research-sources.mjs` in `public-web`. Review its
   unresolved report and inspect authoritative sources for exceptions.
3. Run `node --test tests/research-catalog.test.mjs`, `npm run test:sites` and
   `npm run build`. Review identity, duplicate, locale, source and related-link checks.
4. Inspect actual desktop/narrow rendering, language preferences, both themes,
   pagination, filters, global search, saved links and source/detail navigation.
   Execute generated notebooks with the standard-library checker; use
   `scripts/verify-tutorial-jupyter.py` in an isolated Jupyter environment for
   actual-kernel acceptance. Kernel execution does not certify the Jupyter UI.
5. Commit only scoped content/UI/docs/build changes through the feature PR.
   CI, merge and production publication are distinct states requiring fresh evidence.

This is a maintainable editorial workflow, not an automatic web-ingestion or
publication job. No recurring automation, provider call, account permission or
production collection change is introduced. A later update should state its
selection window and quality evidence instead of promising indefinite freshness.
