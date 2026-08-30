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
This refinement deepens the Tokenomics orientation only; it does not certify all
200 records as full-length guides or full-text reviews.

System language is the default; Account holds the System/中文/English override.
Reader titles, summaries, data requirements and authored limitations change
together. Original titles, author names, DOI, identifiers and source links remain
stable. Source sites/full text may be in another language; this is disclosed.

The first screen remains question-led. Three actual four-record reading paths
lead to stable detail routes. The full library is paginated, with topic/format
filters; global search covers both languages across all records. Counts derive
from assembled records, never manually padded totals. Reading-time estimates
refer only to concise orientations, not to reading the original full papers.
Question and full-library entries reset incompatible format/page filters. Direct
filter changes reset page; record navigation preserves the in-tab library filters,
page and scroll position. This is not cross-device or reload-persistent reading
history. Clipboard failure exposes a selectable citation instead of claiming success.

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
