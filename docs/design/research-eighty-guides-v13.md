# Research continuation: eighty guides and reasoned comparisons

2026-08-31 candidate on `codex/research-depth-quality-v2`, dependent PR #400.
Contract: `docs/product/RESEARCH_LIBRARY.md`. This is not release acceptance.

## Scope and implementation

Preserve all 200 bibliography identities, original authorship, language-neutral
source/bookmark URLs and the eight three-stage core journeys. Add two batches of
ten guides only after inspecting usable primary passages. `researchSeventyGuides.js`
and `researchEightyGuides.js` contain original bilingual commentary, source-specific
locators, version limits and internal actual-reading scopes. No full-text translation,
numerical replication, investment conclusion or provider activation is implied.

The library now has 80 bilingual guides: 79 with six sections, plus Dechow/Dichev's
four-section abstract-based orientation. The remaining 120 works are summary-only.
Source availability was not used to invent new bibliography identities. Stationary
Bootstrap and the textual-analysis survey remain summary-only: usable target full
text was not obtained. The original BH paper and All That Glitters were inspected
instead, both already in the library.

All 200 material selections remain explicit. The new twenty guides intentionally
select no related products/tutorials; the library now has 75 nonempty selections
and 125 empty selections. Empty means no suitable maintained preparation material
was selected, not that the paper has no underlying data. No original sample,
general econometrics tool or production dataset is implied by these guides.

`researchConnections.js` adds 29 explicit comparison pairs across 39 works,
including every new guide and Lazy Prices. Reasons contrast definitions, samples
or methods; these are editorial associations, not inferred citations or endorsement.
The reader preserves the core previous/next sequence and adds at most three
comparisons, excluding existing sequence links. A three-link cap means not every
pair appears in both directions on highly connected articles. Uncurated articles
without a sequence retain the existing same-topic fallback. Selection needs only
metadata and remains available during body loading/error. Existing typography and
navigation classes are reused; no new style system, account state or API.

## Primary-source scope

Search used Exa and direct primary PDF retrieval. The source selection is curated,
not a systematic review. Search snippets, HTML error bodies and unrelated editions
were not treated as inspected target full text. PDFs were parsed, the stated
passages read, and the key pages below visually checked. DM's body scan required
image reading. Exact URLs and section-level locators are in the two source modules;
hashes below identify the retrieved bytes, not a redistribution licence. PDFs and
rendered source images stay outside the repository and product build.

| Existing work | Actual edition and read scope; visual check |
| --- | --- |
| HAR realized volatility | 2009 journal, pp. 174–181, sections 1–2.3; printed p. 177. RV uses the square root of summed squared returns; weekly averaging is a different operation from multi-day aggregation. |
| GARCH | Author-hosted 1986 journal, pp. 307–311; printed pp. 309–310. Finite variance, strict stationarity and higher moments are distinguished. |
| White covariance | 1980 journal scan, pp. 818–822; printed p. 820. Independent observations and orthogonality, not arbitrary serial robustness. |
| Multiway clustering | 13 May 2008 draft, pp. 1–10; printed p. 8. Not silently relabelled as final 2011 tables. |
| Comparing Predictive Accuracy | 1995 JBES scan, printed pp. 254–255 visually read. Mean-loss null, long-run variance and median-loss sign test are different objects. |
| False discovery rate | 1995 JRSS B, pp. 290–293; printed p. 293. Original independence setting and expected proportion, not a posterior probability for each discovery. |
| Liquidity Risk and Expected Stock Returns | August 2001 Wharton draft, printed pp. 1–4; printed p. 4. Own-stock illiquidity differs from exposure to aggregate liquidity innovations. |
| One Security, Many Markets | 1995 JF scan, pp. 1176–1179 and 1182–1183; printed p. 1183. Common trend and ordering-dependent information-share bounds. |
| Algorithmic trading and liquidity | Author-hosted 2011 JF article, pp. 3–8; printed p. 7. Message-based proxy and Autoquote identification, not observed algorithm ownership. |
| Equity premium puzzle | 1985 JME, pp. 145–146, 150–151 and 154; printed p. 150. Representative-agent calibration, not a forecast of today's premium. |
| Time Series Momentum | Author-hosted 2012 JFE, pp. 228 and 231–233; printed p. 233. Own-past returns, contract construction and lagged volatility scaling. |
| Law, Finance, and Economic Growth in China | 3 February 2004 draft, cover and printed pp. 1–5; printed p. 4. Seventeen regional interviews refer to this early draft, not the final 2005 sample. |
| Capital structure puzzle | MIT April 1984 paper 1548-84, printed pp. 1–6, 9–10 and 14; printed p. 9. Trade-off and pecking-order reasoning, not a current optimal leverage estimate. |
| Investor Protection and Corporate Governance | NBER 7428, December 1999 precursor titled Investor Protection: Origins, Consequences, Reform; pp. 1–4, 6, 15 and 20; printed p. 6. Canonical 2000 journal identity remains separate. |
| Disclosure literature review | 2001 JAE, pp. 407–410, 420 and 426; printed p. 408. Information asymmetry, disclosure incentives and endogeneity, not a new causal estimate. |
| All That Glitters | Author-hosted 2008 RFS, pp. 785–788; printed p. 788. Consideration sets, attention proxies and buyer/seller asymmetry, not sentiment polarity. |
| In Search of Attention | 3 June 2010 draft, printed pp. 1, 5–6 and 8–9; printed p. 6. Historical ticker ambiguity, sampling and zero suppression, not current Google Trends API behavior. |
| FAVAR | NBER 10220, January 2004, printed pp. 1–9; printed p. 8. Factor extraction, identification and generated-regressor uncertainty, not replacement-policy-rule effects. |
| Credit Spreads and Business Cycle Fluctuations | NBER 17021, May 2011, printed pp. 3–4, 11–12 and 18; printed p. 11. Cash-flow-matched benchmark, retransformation and model-dependent EBP residual. |
| Blockchain economics | NBER 22952, December 2016 revised June 2019, printed pp. 3–4, 6, 12–13 and 23; printed p. 12. Verification versus networking costs and the offline-input boundary. |

Acquisition exceptions: the UChicago credit-spread PDF address returned HTML and
was rejected; the actual NBER PDF was used. A differently titled Harvard governance
file was not substituted for the linked NBER precursor. SSRN survey access failed;
no full-text review was claimed. The GARCH author-hosted Duke copy was usable after
another host failed. Draft versions are visible in the public locators/limitations;
internal acquisition logs and dates are not shown as reader-facing status panels.

### Retrieved PDF SHA-256

Keys correspond to the table above in order. These are an internal evidence ledger.

```text
HAR          18c305635feefc152a0522791de67677b5db037dd10958a09134c7d55cf222e5
GARCH        60353d437aadda9179df4e7cfcc55f0dd343840b04c6ee7d83285eb33fa17e1a
White        2ba38f3f36ad691ca4ef7ddb36ef76b25b0d81794600b13406e8e12295316f61
Clustering   51c7b7534b299f28736f1fe664f5a629fd2ba79717ecc38dc08b980bfe053022
DM           7f4306f4a714562c9156460cce11b92e82fbfff0d90982a858f25b890dc27c4e
FDR          4d56c465dd4dfd6bcfd97f92acdc17f8d535325d6e760dc5a4ce5427b9766229
Liquidity    5c7e563bab440a86cd394e18ee7c7153c58603b0d157ce5c66e54a24b036dd37
Discovery    b9c1218b1353f988b06ad2a1de73cf9b82bc3a4a3f6686a085f117576c695907
Algorithmic  58a8b9dff3e716db2db69d5ecf1cf6c1ec868ccf78acc879e59c301221480f3c
Premium      e6bf90481b9a05c91caa1f465038dfbb014ab392715562e7a3a35fd6fb25890b
Momentum     7682f8e97eb4b77591dc85e36731ff51ed031970cdde81678108734db9478379
China        182cc9840957ebaaf62c7d9b52fb526750277978233515fada4e913d85b1a2a2
Capital      4b379d0213170fa50844ab3112b80ea5469760a1bd4b95b38e0eeafea45afc98
Protection   a61680071f176a25fbc05ec68f2f0fccb1e6b04a65fcbb7a9ed58792b086cac7
Disclosure   7e43bd741528eded2abd687300e67d88784991bbbd99d5b7111c45964b4222c0
Glitters     7ff115a4e68d9f18178e91fa587ff7a46d448d629d518187558f005911446c19
Attention    550a8c2aa07251cb97cdc4a9fd22ae21c71df1326c42832aed63c7922ce34e9c
FAVAR        547b0a69ca4811a6e2599598e70f7ed7d9d65517b53ceae036698c0c73480934
Credit       6eef919ff73868892f6511d70d893667d10cdd50c05c0a2660ab242243b4dda6
Blockchain   e59a35b9b535b66c163a3b579dbb9276083ece53c22c04049dd845b6c46b868a
```

## Local verification and remaining gates

`npm run build` and all 121 `npm run test:sites` tests pass. The build emits 80
separate non-initial guide modules, 211 static metadata entries and the existing
24 synthetic teaching artifacts. Tests compare every built guide payload with its
authored source and render every record in both languages without internal QA text.
Additional checks cover twenty guide scopes, unique/resolving pairs, metadata-only
comparison selection, the three-link cap, exclusions, loading/error navigation,
locale-specific reasons, core-sequence retention and uncurated fallback.
Notebook code-cell tests run as scripts; this is not a fresh real-kernel or native
save/open pass. Tutorial sources and artifact content are unchanged this increment.

Offline audit: zero structural errors, 120 summary-only records and the existing
seven `check_reading_scope` review cues. These regex cues are not cleared or treated
as proof of incomplete/full reading. No numerical replication was performed.

Final on-disk JavaScript bytes (raw / per-file gzip): research discovery
158,009 / 46,666; main application 331,841 / 98,265; React vendor 193,010 / 60,259.
The combined three files are 682,860 / 205,190, versus 666,860 / 199,521 for v12.
Authored comparisons add initial navigation text while the twenty bodies stay
deferred. These are emitted-file sizes, not measured device speed or network time.

Browser access remains blocked by the earlier tool policy rejection. No alternate
browser, port, CDP route or indirect execution was used to bypass it. Real mobile
layout, physical touch, keyboard/focus, spoken screen-reader output, theme contrast,
slow-network retry, native download/save/open and section-scroll behavior remain
unverified. Server-side markup tests and source-PDF images do not close those gaps.

PR #385 is still the predecessor and #400 remains draft without independent Datas
PM approval. Exact-head CI is to be recorded on the PR after candidate push; prior
head CI cannot certify this increment. Do not self-apply `pm-merge`, merge into the
predecessor as a shortcut or publish. After permitted real-browser acceptance and
independent PM review, land #385, integrate/retarget #400 to main, rerun exact-head
CI, then separately verify merged SHA, exact-main CI, publication and public routes.
Rollback is a scoped revert of this increment's source, tests, docs and rebuilt dist;
no backend, dependencies, workflow, secrets, data, accounts or production changed.
