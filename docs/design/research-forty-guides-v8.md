# Research: forty distinct guides

2026-08-30. Public-web editorial continuation on `codex/research-depth-quality-v2`,
draft PR #400, dependent on #385. This is candidate content, not publication or
production evidence. Entry contract: `docs/product/RESEARCH_LIBRARY.md`.

## Scope and editorial decisions

The library retains 200 works, with 40 bilingual guides (39 six-section and one
four-section abstract-based Dechow/Dichev orientation), 160 summary-only records,
eight three-stage core journeys/24 works, six tutorials and 24 offline artifacts.

`public-web/src/researchMethodsMarketsGuides.js` adds eight new guides: Sharpe
CAPM, Fama/French five factors, Baker/Wurgler sentiment, Liu/Tsyvinski crypto,
Baker/Bloom/Davis EPU, Newey/West covariance, Efron bootstrap and Tibshirani Lasso.
It also replaces the existing China market guide with more specific measurement
explanations. That replacement is not counted as a new guide or another work.
The existing Fama/French 1993 guide's repeated intercept/fit explanation is replaced
with the NYSE sorting-breakpoint convention, preserving its other sections.

Chinese and English were compared for measure direction, denominator, timing,
edition and inference limits. This is editorial checking, not independent expert
review. Explanations distinguish factor returns from firm characteristics,
attention from emotional tone, price information from realized returns,
positive semidefiniteness from invertibility, bootstrap from permutation, and
Lasso constraint bounds from penalty weights. No financial recommendation,
replication, current provider capability or PDF redistribution is introduced.

## Sources and actual inspection scope

URLs and per-section page references live with each guide. The following are
bounded reading scopes, not declarations that every page was reviewed.

| Work / edition | Inspected passages | Visual cross-check |
| --- | --- | --- |
| Sharpe, 1964 journal | pp. 425–426, 431–434, 436–437, 439–440 in matching scan; UW-hosted pp. 433–434, 439–440 checked directly | p. 433 |
| Fama/French, 2015 journal | pp. 1–4, definitions, accounting dates and sample | p. 3 |
| Baker/Wurgler, 2006 journal | pp. 1648–1651, 1653–1657, conceptual channels and proxy construction | p. 1657 |
| Liu/Tsyvinski, August 2018 NBER draft | pp. 2–5, assets, windows and attention/valuation proxies | p. 4 |
| Carpenter/Lu/Whitelaw, 2021 journal | pp. 680–682, information measures, investment and ownership | p. 682 |
| Baker/Bloom/Davis, 2016 journal | pp. 1598–1600, 1605–1606, newspaper counts and normalization | p. 1599 |
| Newey/West, February 1986 revised NBER draft | image-only pp. 1–4, moments, weights and PSD construction | all four pages |
| Efron, 1979 journal | pp. 1–3, target distribution and one-sample construction | p. 3 |
| Tibshirani, 1996 journal | pp. 267–269, 273–275, constraint, scaling and tuning uncertainty | p. 268 |
| Fama/French, 1993 journal | PDF pp. 4–6 for the replacement explanation | printed p. 8 |

The crypto and covariance guides identify their 2018/1986 draft editions publicly
while retaining 2021/1987 journal identities. Neither claims final-edition numerical
equivalence. Other bounded reading scopes remain unchanged. Beneish was considered
but not expanded because a satisfactory primary-text route was not established.

## Maintenance observations

The pre-expansion sweep checked all 242 then-active unique URLs using the existing
read-only checker, concurrency two and an 8-second deadline per request:

- 109 reachable responses, not content verification;
- 112 access-restricted responses;
- 18 network errors, one timeout and one 503 requiring retry/review;
- one confirmed 404: BIS Working Paper 1183's former `/publ/work1183.htm` page.

The BIS publication's new official route was located and its title/authors checked:
`https://www.bis.org/publications/working-paper-1183-why-defi-lending-evidence-aave-v2`.
Only the source URL changed; the existing work and bookmark IDs remain. A targeted
follow-up checked that route plus nine guide PDFs: all ten returned 200, with the
nine PDFs returning `application/pdf`. The current active source set has 250 URLs;
the replaced China preview link is no longer an active guide source. Restricted,
timeout and transient results are not reclassified as broken, accessible or reviewed.

All 186 DOI-bearing records were checked against registered title, authors, venue,
year and DOI: 186 matched. This does not certify the latest full-text edition or
exclude corrections absent from the registration response. Fourteen non-DOI records
were covered by structural and link checks, not this DOI metadata comparison.

The final offline audit has zero structural errors, 160 summary-depth candidates
and six existing reading-scope follow-ups. It found no duplicate identities,
missing translations or exact repeated paragraphs. A semantic repetition in the
1993 guide was found manually and replaced; absence of an exact duplicate is not
a guarantee that all 200 summaries have independently reviewed meaning.

## Verification and residual release gates

- `cd public-web && npm run build && npm run test:sites`: build passed, 91 tests
  passed. Includes 200 records rendered in both languages, identity/count checks,
  source/edition projection, tutorial execution and JS/Python parity.
- Build generated 211 metadata entries and 24 artifacts; the catalog chunk is
  380.34 kB / 129.03 kB gzip. Generated files were rebuilt, not manually edited.
- All 24 local HTTP download bodies matched their generator byte-for-byte. This
  verifies delivery content, not the browser's native save-to-disk completion.
- Nine methods/markets pages rendered in both languages in the app browser with
  their six source links and source-specific limits. Chinese desktop pages had
  no document-level horizontal overflow. Crypto Chinese body was visually read.
- Sharpe and Newey/West English/dark headers and action wrapping were visually
  checked at 390px and 768px using same-build iframe viewports. This is not native
  mobile/touch acceptance, full-body mobile verification or inner-frame width
  measurement; the bridge does not expose frame documents for that check.
- Company Topics page 2 -> Law and Finance -> bookmark -> return retained the
  topic and page. After changing language through Account, the same source was
  saved in English. The test bookmark was removed afterward. This verifies
  identity/filter/page continuity, not OS-language changes or scroll restoration
  across every preference-navigation sequence.
- Complete keyboard traversal, actual mobile touch, spoken screen-reader output
  and native browser download completion remain unverified. Earlier input-bridge
  limitations are not presented as an application defect or a passing test.

PR #385 and #400 remained open without reviews or `pm-merge` at this pass's readback.
The user was asked to identify the independent Datas PM reviewer; no role was
invented or go-ahead self-applied. After predecessor integration and review, retarget
the candidate to main, rerun exact-head CI, then separately verify exact-main CI,
publication and the production route. A green candidate is not that sequence.

No protected Worker/Sites files, dependencies, lockfiles, workflows, backend,
provider registry, credentials or production state changed. Rollback is a scoped
revert of this candidate; generated old hashes remain recoverable in Git.
