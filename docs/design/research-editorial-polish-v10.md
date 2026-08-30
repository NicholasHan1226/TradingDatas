# Research editorial polish and reading acceptance

2026-08-31 Asia/Shanghai; source-reading date 2026-08-30 UTC.
Candidate: `codex/research-depth-quality-v2`, PR #400, dependent on #385.
Entry: `docs/product/RESEARCH_LIBRARY.md`. This is not production evidence.

## Editorial pass

Read the effective Chinese and English bodies and limitations of all 43 guides
for translation consistency, measurement definitions, repeated generic prose and
unsupported inference. This is a current editorial pass, not a fresh full-text
review of all 43 papers. Previous reading scopes remain bounded to their recorded
editions/pages; source-check dates are not advanced by a library-wide edit.
The library remains 200 distinct works, 43 guides (42 six-section, one four-section)
and 157 summary-only records. No canonical citation, record/bookmark ID, topic,
core journey, question-route membership or tutorial calculation changes.

Source-specific changes:

- **Lazy Prices:** [March 2019 NBER revision](https://www.nber.org/system/files/working_papers/w25084/w25084.pdf),
  introduction and printed pp. 11–14, with pp. 11–14 visually checked. Replace two
  generic sections with same-quarter/prior-year pairing, text extraction, the
  numeric-table threshold, and distinctions among cosine, Jaccard, edit distance
  and simple similarity. Keep the prior disclosure-date example and the separate
  final publication identity. No numerical return or formula implementation claim.
- **Corporate Governance and Equity Prices:** [August 2001 NBER draft](https://www.nber.org/system/files/working_papers/w8449/w8449.pdf),
  printed pp. 9–14 visually read; PDF character extraction is encoded. Add binary
  equal-weight limitations, the reverse coding of secret ballots/cumulative
  voting, and firm-level opt-outs from state provisions. Preserve historical
  applicability and the 2003 canonical citation, not current legal guidance.
- **Dechow/Dichev:** [July 2001 author-deposited abstract](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=277231)
  supports firm-specific regressions, one aspect of earnings quality and the
  future-cash-flow boundary. Add direct abstract locators to the three conceptual
  sections; the fourth remains explicitly editorial application. Do not expand
  to six sections or claim exact final-version sample/formula validation.

Exa discovery used four queries of five results (20 returned results, not 20
independently read primary texts). The Michigan archive PDF fetch returned 403,
its text fetch timed out, and a bounded direct request returned HTML rather than
PDF. SSRN delivery timed out. These are access/format gaps, not proof of deletion.
No source PDFs are redistributed. The usable NBER PDFs were inspected locally.

## Maintenance correction

The existing internal-note check previously inspected only section bodies. It
now covers all bilingual fields passed through the maintenance validator,
including headings, summaries and limitations. A mutation test proves that
developer-note strings in these fields are rejected. Internal evidence scope is
still retained internally and excluded from the reader bundle.
Remove stale 26-guide/160-summary current-tense descriptions from the frontend
README; retain historical dated reports without rewriting their past counts.

## Acceptance and release

Fresh candidate acceptance:

- All 99 frontend tests pass, including four new source-definition/internal-note
  regression tests. `npm run build` and `git diff --check` pass; generated outputs
  are rebuilt normally. Catalog output is 399.80 kB / 135.77 kB gzip.
- Offline audit: 200 works, 43 guides, zero structural errors, 157 summary-only
  candidates and six reading-scope flags. Fewer flags reflect the newly recorded
  Lazy Prices reading scope, not certification of the whole library.
- All 24 local HTTP download bodies match the generators. All 12 shipped notebooks
  execute their four code cells in real isolated Jupyter kernels. Artifacts remain
  unchanged; no dependencies, global kernels or provider access were added.
- Browser: Chinese bookmark survives switching to English with the same article
  identity; test bookmark removed afterward. Citation copy shows its success state
  (clipboard contents not independently inspected). Contents click focuses its
  section below the header; reopening Lazy Prices section 3 gives 110.19px top
  clearance and no desktop horizontal document overflow.
- Company-topic page 2 -> governance -> explicit return preserves topic and page.
  A repeated cycle restores exactly the observed 348.5px list scroll position.
- Chinese/light mid-body layout of all three changed guides was visually inspected
  at 390/768px; English/dark Lazy Prices and governance mid-body layouts were also
  inspected. These iframe checks are not native touch-device acceptance. Final
  preview restored to Chinese/light; temporary fixture server stopped.
- A tool-driven Enter attempt did not toggle native contents disclosure, while
  clicking did. Keyboard traversal remains inconclusive, not certified or treated
  as a reproduced application defect. Spoken screen-reader output, native mobile
  touch, browser save completion and actual Jupyter UI opening remain unverified.

No CSS, route, account, dependency, workflow, backend, permission or production
change in this increment. Rollback is a scoped revert of source, docs, tests and
generated frontend outputs.

At preflight, CI 33322852559 succeeded for previous head 1cc1da7; this does not
validate a subsequent commit. PR #385 is still open; PR #400 is draft, based on
the predecessor branch and has no independent `pm-merge` go-ahead. Main
integration, exact-head CI, independent Datas PM release review and production
readback remain separate requirements. Never merge into the predecessor branch
to bypass the main-branch gate.
