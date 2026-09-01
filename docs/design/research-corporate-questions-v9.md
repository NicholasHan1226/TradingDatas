# Corporate guides and question-led reading

2026-08-31. Candidate continuation on `codex/research-depth-quality-v2`, PR #400,
dependent on #385. Entry: `docs/product/RESEARCH_LIBRARY.md`. Not production evidence.
The pass date is Asia/Shanghai; `reviewedAt` is 2026-08-30 UTC to match the
maintenance checker's UTC clock, not a future date immediately after local midnight.

## Scope

Keep 200 works; expand three existing records to six bilingual sections each.
There are now 43 guides (42 six-section; one four-section Dechow/Dichev orientation)
and 157 summary-only works. Original identities, eight core journeys / 24 works,
three curated path pages, six tutorials and 24 generated downloads remain intact.

Three supplementary questions connect nine existing guides: earnings quality,
company comparison and financial distress. Closed disclosures on the first
unfiltered company-topic page avoid expanding another long shelf by default.
Member articles show their relevant question with the current reading marked.
Links retain original article identities; this is editorial sequencing, not a
claim of author citation, causal validation or a new research result.
Expanded articles have a native contents disclosure before the body on desktop
and narrow layouts. Locale-neutral fragment links target focusable sections;
scroll margin keeps section headings clear of the floating navigation.
Browser inspection found that the generic route-entry reset discarded section
fragments on reopening an article. Research-record entry now honors validated
`#research-section-N` targets before the existing scroll reset. Unknown/missing
targets retain the existing fallback, and other route families are unchanged.

## Sources and reading scope

- Dechow/Sloan/Sweeney (1995): journal scan at
  `http://sseriga.free.fr/course/uploads/FA%20-%20PM/Dechow_et_al_1995.pdf`.
  Printed pp. 193–198 text inspected and pp. 199–201 visually read. Public locators
  use canonical DOI `10.2308/tar-9505096112` because the scan host is HTTP-only.
  Distinguishes event-period receivables adjustment from estimation-period fitting,
  proxy errors from misconduct, and sample design from general detection claims.
- Ohlson (1995): METU course-hosted journal scan at
  `https://users.metu.edu.tr/mugan/Ohlson%201995%20earnings%20bv%20div%20in%20eq%20valuation.pdf`.
  Printed pp. 664–668 visually read, covering clean surplus, net distributions,
  beginning-equity capital charge, terminal condition and information dynamics.
  Publisher abstract checked for edition identity. Later proofs not reviewed.
- Altman (1968): matching journal scan at `https://calctopia.com/papers/Altman1968.pdf`.
  Printed pp. 592–596 text inspected (p. 594 visually), plus pp. 602 and 609 for
  loss-making comparisons and sample limits. Publisher title/author/venue checked.
  No score calculation, classifier deployment or accuracy claim is introduced.

Exa discovery used six five-result searches (30 returned hits, not 30 independently
reviewed sources). Original scans, not search snippets, support the authored prose.
The non-institutional scan hosts are access copies, not licensing authorities;
no PDFs are committed, hosted or redistributed. Numerical tables were not replicated.
Jones (1991) was searched but not expanded without a suitable inspected text.

## Acceptance and release

New tests cover three guide identities, both authored languages, nine route
memberships, stable links, collapsed index disclosures and the current-read marker.
- `npm run build` passed; `npm run test:sites` passed all 95 tests. The contents
  target and route-entry fragment tests were observed failing before implementation.
- Offline content audit: 200 works, 43 guides, zero structural errors, 157 depth
  candidates and seven reading-scope flags (including Ohlson's explicit mention
  of a publisher abstract identity check alongside visually inspected full-text pages).
- Generated 211 metadata pages and 24 tutorial artifacts. Catalog chunk:
  398.19 kB / 135.19 kB gzip. No generated content was hand-edited.
- All three new articles were opened in Chinese/light and English/dark: each
  rendered six located sections, six contents links and one relevant question
  route, with no desktop document-level horizontal overflow.
- Native contents clicks in both languages moved focus to section 3 with its
  heading approximately 110px below the viewport top. Reopening the English
  fragment URL after the fix retained that target and clearance.
- English/dark Dechow middle-body wrapping and section placement were visually
  checked in 390px and 768px iframe viewports. This is narrow-layout evidence,
  not native mobile touch acceptance or a full-library mobile audit.
- All 24 HTTP download bodies matched their generator exactly. All 12 notebooks
  executed their four code cells successfully through the existing isolated
  Jupyter acceptance script; shipped notebooks remained unchanged. No global
  kernel registration or new dependency installation was performed.
Native touch, spoken screen-reader output and browser save completion are not
inferred from simulated viewports or HTTP delivery. Previously confirmed keyboard
search selection does not constitute full-page keyboard traversal.

Publish only after independent Datas PM go-ahead, predecessor integration,
exact-head CI and separate exact-main publication/readback. This pass does not
self-apply `pm-merge`. Rollback is a scoped revert including regenerated assets.
No dependencies, protected Worker/Sites files, backend, credentials or runtime
are changed by this content/UI increment.
