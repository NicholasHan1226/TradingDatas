# Fifty bilingual research guides

2026-08-31; candidate branch `codex/research-depth-quality-v2`, dependent PR #400.
Entry: `docs/product/RESEARCH_LIBRARY.md`. Not a production or replication claim.

## Scope

Seven existing bibliography identities gain six-section bilingual guides, bringing
the candidate to 50 guides (49 six-section; Dechow/Dichev remains four-section),
within 200 distinct works. The remaining 150 records are summary-only. Preserve
citations, bookmark IDs, core journeys, question routes and tutorial calculations.

Primary sources and bounded reading:

- CoVaR: NY Fed Staff Report 348, September 2014 revision, introduction and
  sections 3.1–3.5; printed p. 7 visually checked.
- Liquidity and Leverage: NY Fed Staff Report 328, December 2010 revision,
  introduction and printed pp. 4–12; p. 8 visually checked.
- Text as Data: author-hosted 2019 JEL article, section 2 and opening of section 3,
  pp. 537–541; p. 537 visually checked.
- Measuring Geopolitical Risk: official IFDP March 2022 cover / November 2021
  manuscript, sections I.A–I.E; printed p. 5 visually checked.
- Random Forests: Berkeley January 2001 author manuscript, sections 1–4 and 10;
  p. 8 visually checked. Preserve the separate journal citation.
- Chinese Warrants Bubble: author-hosted 2011 AER article, introduction and
  section I, pp. 2723–2728; p. 2727 visually checked. Historical rules only.
- DeFi Risks and the Decentralisation Illusion: official December 2021 BIS HTML,
  overview, building blocks, governance and vulnerabilities sections. Not a
  current protocol, chart-value, legal or security audit.

Exact source links and section locators live in `researchFiftyGuides.js`. Six
PDFs downloaded and inspected locally; no paper PDFs or quoted abstracts shipped.
Exa: eight queries of five results, 40 returned hits, not 40 independent source
reviews. One exploratory price-informativeness paper was not selected because it
was outside this seven-record existing-library batch. Seven primary pages fetched.

## Material links

Guide-specific `related` overrides can now replace category defaults; an explicit
empty object suppresses unrelated products. CoVaR links only to price preparation;
leverage to as-of disclosure alignment; Text as Data/GPR to document versioning.
The text explains what these tutorials do not provide. Warrants, Random Forests
and DeFi have no appropriate ready-made material bundle and use no product links.
This is methodological navigation, not data entitlement, activation or replication.

The original 43 guides now use explicit selections in `researchGuideMaterials.js`.
Daily high/low and Amihud point to daily data; text guides to document versions;
event studies to event/price preparation. Order-book/transaction-level studies,
governance, general fitting estimators, Bitcoin governance and token adoption have
no suitable ready-made bundle and suppress inherited links. Yield curves and
single-venue crypto retain only relevant exploratory data, not original samples.
All 200 records are checked for resolving material IDs; semantic curation in this
pass covers the 50 guides, not the other 150 summary records' topic defaults.

## Acceptance and release

Fresh local checks on 2026-08-31:

- All 104 frontend tests pass, including 400 record/locale server renders, stable
  identities, per-guide material choices, empty-disclosure rendering and synthetic
  JS/Python agreement. Server renders do not establish browser interaction.
- Production build passes: 211 static research/tutorial entries and 24 teaching
  artifacts. Research catalog chunk is 436.88 kB / 149.82 kB gzip; no performance
  benchmark claim. This larger content bundle remains a future loading concern.
- Offline audit: 200 works, 50 guides, six tutorials, zero structural errors,
  150 summary-only candidates and six limited-reading-scope flags retained.
- All 24 built teaching artifacts match generator bytes. All 12 notebooks validate
  with nbformat and execute all four code cells in separate real Python kernels.
  Execution occurs in memory; distributed files retain clean, unexecuted cells.
- Browser initially failed because the preview was unavailable. After restoring
  the existing preview, browser policy blocked reload. No alternate browser/CDP/
  port workaround was attempted. This turn has no successful rendered-browser QA.
  Keyboard traversal, spoken screen-reader output, native touch and browser
  download/save/open remain unverified; prior-turn visual checks are historical.
- No CSS, route, tutorial calculation, dependency, workflow, backend, registry,
  credential, authority or production change. Rebuilt dist is included. Rollback
  is a scoped revert of this candidate commit, including its generated outputs.

PR #385 remains open and #400 remains draft on its predecessor branch. Independent
Datas PM review and `pm-merge` are still required for main integration; do not
self-apply a label or merge into the predecessor branch to bypass review. Update
PR #400 with the new exact-head CI result after pushing; prior-head success does
not certify this increment. No main merge, publication or production is claimed.
