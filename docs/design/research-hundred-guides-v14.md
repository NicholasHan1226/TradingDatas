# Research: 100-guide candidate and independent acceptance packet

Scope: PR #400 on `codex/research-depth-quality-v2`, stacked on PR #385. This is a candidate record, not approval or a production claim. Last checked 2026-08-31.

## Frozen change scope

- Keep all 200 bibliography identities; expand bounded original bilingual guides from 80 to 100.
- Add authored comparison reasons for uncovered guides without changing the eight core journeys.
- Preserve system/manual language, metadata-only discovery and per-record lazy bodies. No backend, entitlement, price, collection or deployment change.
- Source editions and inspected pages belong in this record; public articles retain source attribution and specific limitations, not internal QA panels.

## Independent review handoff

| Gate | Evidence required | Current state |
| --- | --- | --- |
| Content | Verify source edition, inspected-page support, bilingual meaning and all 200 identities | Primary passages and local checks documented; independent review pending |
| Reader acceptance | Mobile/desktop, Chinese/English, light/dark/system, anchors, keyboard and spoken reader | Not verified: previous browser restriction remains in force |
| Failure paths | Real slow/failed body loading, retry and navigation without losing identity | Unit coverage is separate; real browser pending |
| Downloads | Actual save, reopen and read all localized file types | Generator checks are separate; real save/open pending |
| Independent Datas PM | Review exact candidate head; grant approval through project PM process | No approval inferred or self-issued |
| Predecessor | Land #385, integrate/retarget #400 to main, rerun exact-head CI | #385 open at a7cf9d42d83fc66f9f887056310c701f58815cb0 |
| Release | Authorized merge, exact-main CI, deployed revision and public route readback | Not performed |

Do not substitute SSR, a different port, terminal-driven browser or a second browser for the blocked browser acceptance. Reopen this gate only through the permitted approval path. Do not merge #400 into its predecessor to bypass main integration.

## Verification and source ledger

Executable checks: `cd public-web && npm run test:sites && npm run build && npm run audit:research`. Final candidate results follow below; real-browser acceptance and independent review remain separate gates.


### Primary-source reading ledger

Twenty usable original documents were retrieved. Exa discovery used 27 successful search calls (135 requested result slots, not 135 verified sources). PDF text was read for the bounded passages below; key pages were visually inspected. Merton and What Moves Stock Prices required scan-image reading. Source files and rendered pages remain outside Git and the product build. Hashes identify retrieved bytes, not redistribution rights or complete review.

The 2014 practitioner abridgment of the politically connected CEOs article was excluded in favor of the original 2007 JFE paper. Media Coverage and Wisdom of Crowds were not expanded from snippets. CSI's retrieved file explicitly says September 2023; the undated author copy of Financial Liberalization remains undated rather than receiving an invented revision date.

| Existing work / source | Edition and actual reading scope | Visual check (printed page) | SHA-256 |
| --- | --- | --- | --- |
| [An Intertemporal Capital Asset Pricing Model](https://breesefine7110.tulane.edu/wp-content/uploads/sites/16/2015/10/Merton-Int.-CAPM.pdf) | 1973 journal article. Printed pp. 867–870 visually inspected from the scanned journal copy: lifetime choice, opportunity sets, market assumptions and asset supply. Later separation results and proofs not reviewed. | 867–870 | `8aea927338deb315b6c9dc9ae87c49e7697c21c9f0f1bc010b67d82a044a3278` |
| [The Arbitrage Theory of Capital Asset Pricing](https://jacobslevycenter.wharton.upenn.edu/wp-content/uploads/2016/10/The-Arbitrage-Theory-of-Capital-Asset-Pricing.pdf) | 1976 journal article. Printed pp. 341–343 inspected, including the factor representation, diversified zero-cost heuristic and the author's explicit warning about its weaknesses. Later formal proofs not reviewed. | 342 | `bcc20d507227cbd9b01cf9c331ce118cf20485d56e4e1ebbaf1e3e1064e94443` |
| [Asset Prices in an Exchange Economy](https://www.economics.utoronto.ca/adamopou/lucas_ap.pdf) | 1978 journal article. Printed pp. 1429–1432 inspected for the exchange economy, endowment process, timing, rational expectations and equilibrium definition. Subsequent proof and quantitative implications not reviewed. | 1431 | `703d382543e41c2bdc7649bf4ab3d7bcc8ea29130944736c24df2a720c33914d` |
| [By Force of Habit: A Consumption-Based Explanation of Aggregate Stock Market Behavior](https://www.bauer.uh.edu/rsusmel/phd/campbell-cochrane_1999JPE.pdf) | 1999 journal article. Printed pp. 205–207 and 209–210 inspected for external habit, surplus consumption, local curvature and consumption dynamics. Simulations and later empirical fit not independently reproduced. | 209 | `188775fd10f7b24b230eb0db72c0a923f41c534bb5d2aca93bac8b7e09a06585` |
| [Risks for the Long Run: A Potential Resolution of Asset Pricing Puzzles](https://msuweb.montclair.edu/~lebelp/BansalRisksForTheLongRunJF200408.pdf) | 2004 journal article. Printed pp. 1481–1485 inspected for persistent growth news, recursive preferences, distinct consumption/dividend claims and Case I dynamics. Full uncertainty-case derivation and calibration not reproduced. | 1484 | `2a97a47ccb2b6a44d82ef6827b868f88c15b0c669b2c3aa922e99063676f4984` |
| [Value and Momentum Everywhere](https://w4.stern.nyu.edu/facdir/lpederse/papers/ValMomEverywhere.pdf) | 2013 journal article. Printed pp. 932–937 inspected for cross-sectional versus time-series momentum, liquid sample selection, return units and asset-specific value measures. Performance and implementation sections not replicated. | 936 | `400da98388d426c97172ddbff80630de6fcee6d54510243a139504486d317393` |
| [Betting Against Beta](https://w4.stern.nyu.edu/facdir/lpederse/papers/BettingAgainstBeta.pdf) | May 10, 2013 draft. Author-hosted draft pp. 3–5 inspected for beta scaling, funding constraints, contemporaneous versus expected returns and the explicit lagged-TED inconsistency. Estimation and trading results not reproduced. | 3 | `1ce429524fe9ee8b1831824a3b5ba1cc7e506ba01e27eec6e44005e68d4c2037` |
| [Risk, Return, and Equilibrium: Empirical Tests](https://people.hec.edu/rosu/wp-content/uploads/sites/43/2023/09/Fama-MacBeth-Risk-return-and-equilibrium-Empirical-tests-1973.pdf) | 1973 journal article. Printed pp. 607–609 and 613–616 inspected for testable restrictions, estimated betas, formation/estimation windows and monthly cross-sectional regressions. Full result tables not reviewed. | 616 | `631c1fcace695784c46ecc20672ba0b4c884831d3cb2fa97a910cd9b5071b969` |
| [Differences of Opinion, Short-Sales Constraints, and Market Crashes](https://www.columbia.edu/~hh2679/hong-stein-rfs.pdf) | 2003 journal article. Printed pp. 488–490 inspected for heterogeneous signals, constrained pessimists, endogenous revelation, asymmetry and contagion. Theoretical motivation only; later formal results not independently verified. | 489 | `b57eaf1b0265ebc833a79cd7dbef30f91a27cc1d2ee2178e1b8b9664b2abe1d2` |
| [Speculative Trading and Stock Prices: Evidence from Chinese A-B Share Premia](https://www.nber.org/system/files/working_papers/w11362/w11362.pdf) | 2005 NBER working paper. Printed pp. 1–3 inspected for resale-option motivation, historical A/B segmentation, matched rights and turnover/liquidity controls. Later regressions and institutional changes not reproduced. | 2 | `b75ab227509d2b970f3e96481068914fc9b0d0fe8caaf564c274f7637344806d` |
| [Stock Market Liberalization, Economic Reform, and Emerging Market Equity Prices](https://www.underpricing.de/files/Henry_Stock-Market.pdf) | July 1999 draft. Manuscript cover and printed pp. 1–4 inspected for liberalization definitions, equity revaluation, event windows, timing selection and concurrent reforms. Journal-version estimates not substituted. | 3 | `ec491ec3de59f77c7e6bf05aa9ff9459c8590a2841e1cfd0983d7d0c0dd14b84` |
| [Does Financial Liberalization Spur Growth?](https://people.duke.edu/~charvey/Research/Working_Papers/W56_Does_financial_liberalization.pdf) | Author-hosted manuscript. Author-hosted manuscript cover and printed pp. 1–3 inspected for real per-capita growth, official/first-sign/intensity measures, selection and simultaneous reforms. Cover has no revision date; no final-version numerical estimate adopted. | 3 | `afa79c03b6f26d91ce17271bdf69fd7e9ba11ccd9a34441e1a20dfc5e3c19280` |
| [Politically Connected CEOs, Corporate Governance, and Post-IPO Performance of China's Newly Partially Privatized Firms](https://cuhk.edu.hk/ief/josephfan/doc/research_published_paper/11.pdf) | 2007 journal article. Journal pp. 330–332 and 335 inspected for CEO definition, 1993–2001 IPO scope, ownership context and coverage differences. This is the JFE article, not its 2014 practitioner abridgment. | 331 | `f85fbd7fcc694c212f1517fec2011eef2860a85d57c7fc45d6f09bf662f34538` |
| [Retail and Institutional Investor Trading Behaviors: Evidence from China](https://www.pbcsf.tsinghua.edu.cn/PDF/yifabiao7.pdf) | 2024 review. Review pp. 460–462 inspected for investor classifications, account-level aggregation, volume versus holdings, US proxy differences and historical efficiency measures. This is a review; underlying proprietary data not accessed. | 460 | `141e813171bb686d73b571b76cd807a880b18ef4483434a3c75ebbfe5da3f06e` |
| [CSI 300 Index Methodology](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/en/000300_Index_Methodology_en.pdf) | September 2023 methodology. Official PDF cover and printed pp. 1–2 and 6–7 inspected for selection, adjusted capitalization, divisor, periodic review and buffers. Historical edition only; current rules and constituent files not verified. | 1 | `e8de553ca0fc0a45870688535047752600779cc2902ce1ed8ff5f701cb0a0e72` |
| [More Than Words: Quantifying Language to Measure Firms' Fundamentals](https://www.uts.edu.au/globalassets/sites/default/files/adg_cons2015_tetlock-saar-tsechansky-macskassy-jf-2008.pdf) | 2008 journal article. Printed pp. 1438–1441 inspected for firm-news coverage, dictionary weights, earnings versus returns, timing/cost limitations and entity matching. Original news corpus and regressions not reproduced. | 1440 | `1f699df9ab34840f98ce41aa550cfa0cf07d98e86c172a6be40e081792d82c80` |
| [The Sum of All FEARS Investor Sentiment and Asset Prices](https://rady.ucsd.edu/faculty/directory/engelberg/pub/portfolios/FEARS.pdf) | October 7, 2013 draft. Author-hosted draft cover and printed pp. 1–2 and 5–7 inspected for term selection, US search scope, quarterly normalization, preprocessing and expanding selection. Later result tables and live Google behavior not verified. | 7 | `ec05f15cc70814c34855ab90aa835dcc0321d308e089790325308d0c4d6a8941` |
| [Investor Sentiment in the Stock Market](https://pages.stern.nyu.edu/~jwurgler/papers/wurgler_baker_investor_sentiment.pdf) | 2007 review. Printed pp. 130–132 and 134–136 inspected for top-down versus bottom-up approaches, hard-to-value/arbitrage stocks and proxy confounding. Composite-index construction and later result tables not reviewed. | 135 | `252f253432d96c5fc9bb4457ba1e9777e4f00ec5625ce6136e729bf3a933f366` |
| [What Moves Stock Prices?](https://www.nber.org/system/files/working_papers/w2538/w2538.pdf) | 1988 NBER working paper. Scanned printed pp. 1–4 visually inspected for news-explanation motivation, VAR innovations, historical windows and omitted-information caveats. Later event tables and numerical decompositions not independently reviewed. | 1–4 | `33aa59aebac07296f2608b19875e75d98795cc7105383e016088ccdf2b327ece` |
| [Annual Report Readability, Current Earnings, and Earnings Persistence](https://www.cis.upenn.edu/~mkearns/finread/readability.pdf) | September 15, 2006 draft. Draft cover and printed pp. 2–4 and 8–11 inspected for readability/length definitions, text filtering, sample dates and obfuscation alternatives. This predates the 2008 article; final-version counts not substituted. | 10 | `02c70ee9e36a078fe1e9325eaf8aed7086febc686d82cb5bd310a4d97b1eec9b` |

### Content and comparison result

100 bilingual guides / 200 bibliography identities; 99 six-section guides and one four-section abstract-based Dechow/Dichev orientation. The other 100 records remain summary-only. Eight core journeys / 24 distinct core works, three question paths, three curated reading paths and six preparation tutorials are unchanged.

New guide coverage: asset-pricing 14/27; A-share 13/17; alternative-data 12/21. The seven A-share additions include historical institutional comparisons, not current policy assertions or collection activation. All twenty retain explicit material selections: three pre-existing preparation links and seventeen empty sets. Global coverage stays 75 linked / 125 empty. Preparation examples are not the historical samples or reproductions.

36 authored symmetric pairs extend the previous 29 to 65 across 101 works, covering every guide even after excluding already displayed core neighbors. Original pairs remain first; display remains capped at three. Reasons contrast definitions, inputs or mechanisms, never inferred citations or endorsement. No browser, backend, commercial, registry, workflow or dependency change.

### Fresh local verification, 2026-08-31

- 124 frontend tests pass. Coverage includes all 200 records in both locales, all 100 guide comparison navigations in both locales and loading/error/ready states (600 SSR combinations), stable identities, deliberate material selections, all-guide authored/built payload equality, and unchanged synthetic tutorial checks. SSR is not a real accessibility or layout acceptance.
- Build passes with 100 deferred guide modules and 211 static metadata entries. The initial three JavaScript files total 702,982 bytes / 211,605 gzip; deferred bodies total 561,859 / 281,229 gzip. Previous candidate initial total was 682,860 / 205,190 gzip. Authored comparison navigation adds initial bytes; guide bodies stay deferred. No device-speed claim.
- Offline audit: zero structural errors; 100 summary-only records and seven pre-existing reading-scope review cues. No short or repeated paragraph cues. Counts and length do not certify whole-paper review.
- All 24 generated download artifacts match their maintained generator byte-for-byte. Tutorial source and download bytes are unchanged. The existing test suite executes notebook cells as scripts; real Jupyter-kernel validation was not repeated this increment. Native save/open remains blocked/unverified.
- `git diff --check` passes. Initial red tests demonstrated the missing 20 guides and uncovered comparisons; the new acceptance tests now pass without weakening paragraph thresholds.
- Exact-head remote CI is to be recorded on PR #400 after the candidate push. Prior-head green CI is not used as evidence for this candidate. Nightly/full timing suites were not selected because no backend/runtime change is in scope.
- Real browser interaction, responsive rendering, theme contrast, keyboard focus, spoken reader, touch and slow-network behavior remain unverified under the existing restriction. No alternate browser, port, CDP or indirect workaround was used.

### Release and rollback boundary

This increment edits the three research content/comparison modules, the guide aggregator and comparison import, targeted tests, two documentation entries, this source ledger, and generated `public-web/dist/client` output. It does not modify CSS, routes, dependencies, lockfiles, workflows, backend, registry, credentials or production. Rollback is a scoped revert of the candidate source/tests/docs and associated build output, not a database or runtime rollback.

At delivery, consult PR #400 for the exact candidate SHA and CI run. It remains draft until permitted reader acceptance and independent Datas PM review. After #385 lands, integrate/retarget to main and repeat exact-head checks before the PM merge gate. Actual merged SHA, exact-main CI, public-site publication and route readback must each be recorded; none is implied by this candidate.
